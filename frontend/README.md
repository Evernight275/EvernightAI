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

## Component Boundaries

`WorkspaceView` subscribes to the state machine. `WorkspaceStatus` and
`WorkspaceIssues` own lifecycle feedback. `WorkspaceContents` composes one
component per domain concept; those components own their counts, formatting,
and empty states. `App.vue` contains no domain rendering logic.

The separate `chat.html` entry renders the chat skeleton. `ChatView` composes
the prerequisite, request form, request status, tool activity, and transcript
components. Its `chatMachine` owns context preparation, agent runs, tool
approval, retry, cancellation, errors, and local conversation history. The
first turn creates a server context; every turn then uses `/agent-runs` with the
Workspace tool catalog so the backend can execute multi-round tool calls. Chat
transitions through `preparing`, `streaming`, `approvalRequired`,
`resumeRequired`, `resuming`, `retrying`, `canceling`, `clearing`, `canceled`,
and `failed`. Each pending tool approval is decided separately after its call
arguments and permissions are shown. Streaming trace events update tool
activity before the final run snapshot arrives. Retries use a preallocated run
id and `/agent-runs/{run_id}/retry/stream`, so an in-flight retry can be
canceled deterministically. `CANCEL` stops a run while retaining local history;
`CLEAR` cancels outstanding work, deletes the server context, and clears local
history.

## Commands

```bash
pnpm dev
pnpm test
pnpm run test:typecheck
pnpm run build
pnpm run check
```
