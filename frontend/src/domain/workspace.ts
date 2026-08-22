import {
  ApiError,
  fetchProviderModels,
  getHealth,
  getReadiness,
  listAgentRuns,
  listDataSources,
  listMemories,
  listSessions,
  listSkills,
  listTools,
  type AgentRunState,
  type DataSourceDefinition,
  type MemoryItem,
  type ProviderInfo,
  type ProviderModelGroup,
  type Session,
  type SkillDefinition,
  type ToolDefinition,
} from '../api'

export type WorkspaceConcept =
  | 'providerCatalog'
  | 'conversationIndex'
  | 'knowledgeIndex'
  | 'capabilityCatalog'
  | 'executionIndex'

export type ProviderCatalog = {
  providers: ProviderInfo[]
  modelGroups: ProviderModelGroup[]
}

export type ConversationIndex = {
  sessions: Session[]
}

export type KnowledgeIndex = {
  memories: MemoryItem[]
}

export type CapabilityCatalog = {
  tools: ToolDefinition[]
  skills: SkillDefinition[]
  dataSources: DataSourceDefinition[]
}

export type ExecutionIndex = {
  runs: AgentRunState[]
}

export type WorkspaceSnapshot = {
  loadedAt: string | null
  providerCatalog: ProviderCatalog
  conversationIndex: ConversationIndex
  knowledgeIndex: KnowledgeIndex
  capabilityCatalog: CapabilityCatalog
  executionIndex: ExecutionIndex
}

export type WorkspaceIssue = {
  concept: WorkspaceConcept
  resource: string
  message: string
  status: number | null
  errorType: string | null
  cause: unknown
}

export type WorkspaceLoadResult = {
  workspace: WorkspaceSnapshot
  issues: WorkspaceIssue[]
}

export function emptyWorkspaceSnapshot(): WorkspaceSnapshot {
  return {
    loadedAt: null,
    providerCatalog: { providers: [], modelGroups: [] },
    conversationIndex: { sessions: [] },
    knowledgeIndex: { memories: [] },
    capabilityCatalog: { tools: [], skills: [], dataSources: [] },
    executionIndex: { runs: [] },
  }
}

export async function loadWorkspace(signal: AbortSignal): Promise<WorkspaceLoadResult> {
  await Promise.all([getHealth(signal), getReadiness(signal)])

  const [providers, sessions, memories, tools, skills, dataSources, runs] =
    await Promise.allSettled([
      fetchProviderModels(signal),
      listSessions(signal),
      listMemories({}, signal),
      listTools(signal),
      listSkills(signal),
      listDataSources(signal),
      listAgentRuns(signal),
    ] as const)

  if (signal.aborted) {
    throw signal.reason
  }

  const issues = [
    issueFrom('providerCatalog', 'providers', providers),
    issueFrom('conversationIndex', 'sessions', sessions),
    issueFrom('knowledgeIndex', 'memories', memories),
    issueFrom('capabilityCatalog', 'tools', tools),
    issueFrom('capabilityCatalog', 'skills', skills),
    issueFrom('capabilityCatalog', 'dataSources', dataSources),
    issueFrom('executionIndex', 'agentRuns', runs),
  ].filter((issue): issue is WorkspaceIssue => issue !== null)

  return {
    workspace: {
      loadedAt: new Date().toISOString(),
      providerCatalog: valueOr(providers, { providers: [], providerModelGroups: [] }, (value) => ({
        providers: value.providers,
        modelGroups: value.providerModelGroups,
      })),
      conversationIndex: { sessions: valueOr(sessions, []) },
      knowledgeIndex: { memories: valueOr(memories, []) },
      capabilityCatalog: {
        tools: valueOr(tools, []),
        skills: valueOr(skills, []),
        dataSources: valueOr(dataSources, []),
      },
      executionIndex: { runs: valueOr(runs, []) },
    },
    issues,
  }
}

function issueFrom(
  concept: WorkspaceConcept,
  resource: string,
  result: PromiseSettledResult<unknown>,
): WorkspaceIssue | null {
  if (result.status === 'fulfilled') {
    return null
  }

  return {
    concept,
    resource,
    message: errorMessage(result.reason),
    status: result.reason instanceof ApiError ? result.reason.status : null,
    errorType: result.reason instanceof ApiError ? result.reason.errorType : null,
    cause: result.reason,
  }
}

function valueOr<T>(result: PromiseSettledResult<T>, fallback: T): T
function valueOr<T, R>(
  result: PromiseSettledResult<T>,
  fallback: T,
  transform: (value: T) => R,
): R
function valueOr<T, R>(
  result: PromiseSettledResult<T>,
  fallback: T,
  transform?: (value: T) => R,
): T | R {
  const value = result.status === 'fulfilled' ? result.value : fallback
  return transform ? transform(value) : value
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'API request failed'
}
