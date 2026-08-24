# EvernightAI Frontend

The frontend currently renders an intentionally unstyled workspace skeleton on
top of the API transport and application state.

## State Model

`src/domain/workspace.ts` groups API resources into frontend concepts:

- `ProviderCatalog`: providers and their available models
- `ConversationIndex`: session summaries
- `KnowledgeIndex`: durable memories
- `CapabilityCatalog`: tools, skills, and data sources
- `ExecutionIndex`: agent runs

`src/state/workspaceMachine.ts` owns the workspace lifecycle:

```text
idle -> loading -> ready
                -> degraded
                -> unauthorized
                -> offline
```

- `degraded` means the API is reachable but one or more concepts failed to load.
- `unauthorized` means a business API returned HTTP 401.
- `offline` means the health or readiness handshake failed.
- `REFRESH` reloads the workspace.
- `AUTH_CHANGED` cancels the current load and starts again with new credentials.

Components should subscribe to `workspaceActor` and send events. They should not
create independent workspace loading flags or call the startup APIs themselves.
The settings page stores API Key authentication through the shared API client;
credential changes emit `AUTH_CHANGED` through the workspace runtime.

## Component Boundaries

`WorkspaceView` subscribes to the state machine. `WorkspaceStatus` and
`WorkspaceIssues` own lifecycle feedback. `WorkspaceContents` composes one
component per domain concept; those components own their counts, formatting,
and empty states. `App.vue` contains no domain rendering logic.

The separate `chat.html` entry renders the chat skeleton. `ChatView` composes
the prerequisite, request form, request status, tool activity, and transcript
components. `ChatSidebar` creates and selects persisted sessions and keeps the
settings entry at the bottom of the layout. Its `chatMachine` owns session
creation/loading, context history, agent runs, tool approval, retry,
cancellation, and errors. Selecting a session loads its persisted Context;
every later turn uses that Context and includes its `session_id` while calling
`/agent-runs`. Chat transitions through `creatingSession`, `loadingSession`,
`preparing`, `streaming`, `approvalRequired`,
`resumeRequired`, `resuming`, `retrying`, `canceling`, `clearing`, `canceled`,
and `failed`. Each pending tool approval is decided separately after its call
arguments and permissions are shown. Streaming trace events update tool
activity before the final run snapshot arrives. Retries use a preallocated run
id and `/agent-runs/{run_id}/retry/stream`, so an in-flight retry can be
canceled deterministically. `CANCEL` stops a run while retaining local history.
For a Session, `CLEAR` empties its Context without deleting it; standalone
Contexts are deleted.

## Commands

```bash
pnpm dev
pnpm test
pnpm run test:typecheck
pnpm run build
pnpm run check
```
