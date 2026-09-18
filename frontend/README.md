# EvernightAI Frontend

设置页现已接入模型服务创建/删除、记忆管理、运行管理和实时轨迹、数据分析。
工作区资源提供上下文、会话归档/恢复、工具与技能、日志等高级入口。
聊天标题旁可编辑会话名称，输入框上方可选择技能及预览上下文。
完整入口映射和普通/流式接口的对应关系见 [INTERFACE_COVERAGE.md](INTERFACE_COVERAGE.md)。

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

The separate `chat.html` entry renders the chat workspace. `ChatView` composes
`ChatHeader`, `ChatTranscript`, `ChatRequestStatus`, the request form, and
`ChatRunDetails`. The header contains a title, an active-run status, and the details entry.
The sidebar supports title search and can collapse on desktop. The empty page
centers the composer beneath a welcome heading; sending the first message
creates a persisted session before starting the run. Approvals and recovery actions live above the composer;
the rounded composer grows with the draft, offers a searchable model picker grouped by provider
inside its bottom row, and replaces Send with Stop while cancellation is available.
User turns appear as right-aligned bubbles and assistant turns as plain text. `ChatRunDetails` is an independently
scrollable side dialog for tool parameters/results, run identity, and diagnostics.
Opening it is local presentation state, not an Agent state transition.
On small screens the sidebar becomes a modal navigation panel, while the
transcript remains scrollable and the composer stays at the viewport bottom.
`ChatTranscript` delegates each visible user or assistant turn to `ChatMessage`;
system and tool records remain outside the conversation view. `ChatSidebar`
creates, selects, and deletes persisted sessions and keeps the settings entry at the
bottom of the layout. Its `chatMachine` owns session
creation/loading/deletion, context history, agent runs, tool approval, retry,
cancellation, and errors. Selecting a session loads its persisted Context;
every later turn uses that Context and includes its `session_id` while calling
`/agent-runs`. Chat transitions through `creatingSession`, `loadingSession`,
`deletingSession`, `preparing`, `streaming`, `approvalRequired`,
`resumeRequired`, `resuming`, `retrying`, `canceling`, `clearing`, `canceled`,
and `failed`. Each pending tool approval is decided separately after its call
arguments and permissions are shown. Streaming trace events update tool
activity before the final run snapshot arrives. Retries use a preallocated run
id and `/agent-runs/{run_id}/retry/stream`, so an in-flight retry can be
canceled deterministically. `CANCEL` stops a run while retaining local history.
For a Session, `CLEAR` empties its Context without deleting it; standalone
Contexts are deleted.
An Agent Run only returns to `idle` after a genuinely finished response.
`tool_rounds_exhausted` remains in `failed` and can continue through the retry
lifecycle instead of appearing as a completed conversation turn.

Assistant text is rendered by `MarkdownContent` through `markdown-it`. Raw HTML
is disabled, unsafe link schemes are rejected, and external links receive
`noopener noreferrer`. Inline `$...$` / `\\(...\\)` and block `$$...$$` /
`\\[...\\]` formulas render with KaTeX using untrusted input mode; user messages
remain plain text.

Visual tokens live in `src/styles/tokens.css`. The interface uses neutral
surfaces, one blue action color, semantic status colors, and no gradients.

## Commands

```bash
pnpm dev
pnpm test
pnpm run test:typecheck
pnpm run build
pnpm run check
```

The browser layout regression uses mocked API responses only. With the Vite
server running, install Playwright Chromium and run:

```bash
pnpm exec playwright install chromium
pnpm run test:browser
```

Linux environments also need Chromium system libraries (`playwright install-deps
chromium`). The test covers desktop, mobile, and short landscape viewports,
large approvals, dialog focus/Escape/backdrop behavior, stopping, approval
decisions, and retry. Interaction coverage also checks provider/model selection,
incremental text before the stream closes, final-response deduplication,
and session deletion (cancel, failure, active-run cancellation, and reload).
`FRONTEND_URL` overrides `http://127.0.0.1:5173`;
`SCREENSHOT_DIR` overrides `/tmp/evernight-layout`. Screenshots stay outside
the source tree. `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` can select an existing
compatible Chromium installation.

Model text deltas update the visible assistant message immediately. Completed
responses replace their partial message; separate tool rounds keep separate
messages. Stopping keeps received text. The transcript follows new text while
near the bottom and lets readers scroll back without being pulled down.
Deleting the selected session cancels its active run before requesting deletion;
failed deletion keeps the session and reports the server error.

Settings open in a modal over the chat workspace, keeping the current chat and
draft mounted. The standalone index entry renders the same settings panel.
General, connection/authentication, and data-control sections expose working
controls; resource details remain expandable. Escape and the close button
return to chat. Mobile layouts use a horizontal category bar.
