# EvernightAI Frontend

Run `pnpm run format` to format frontend source, tests, and configuration.
Run `pnpm run format:check` to check formatting without modifying files.

设置页现已接入模型服务创建/删除、记忆管理、运行管理和实时轨迹、数据分析。
工作区资源提供上下文、会话归档/恢复、工具与技能、日志等高级入口。
聊天标题旁可编辑会话名称，输入框上方可选择技能及预览上下文。
完整入口映射和普通/流式接口的对应关系见 [INTERFACE_COVERAGE.md](INTERFACE_COVERAGE.md)。

The chat, image and settings pages share one neutral visual system on top of
the API transport and application state.

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
tool calls appear between assistant messages as `ChatInlineTool` cards, while
system messages stay hidden. `ChatToolDisplay` renders completed file writes,
appends, text patches, and JSON writes as a unified diff with line numbers;
command tools render captured stdout/stderr and exit codes in a terminal panel.
The panel keeps basic ANSI colours and weights, drops every other escape, and
replaces the one-line text preview. While a command is still running the panel
shows the requested command with an in-progress status.
Both views also appear in run details, with the original JSON available to expand.
File tools save the actual before/after diff in their result, so refreshed history
does not depend on the file's current contents. Diff inputs are limited to 64,000
characters and 2,000 lines, and the saved diff to 12,000 characters. Missing or
oversized snapshots and truncated output are labeled explicitly. Old results
without a saved diff show an unavailable notice. Terminal panels display captured
output after execution; they are not interactive terminals.
`ToolOutput` adds folding, literal text search with match navigation, and copying
to diff, terminal, and raw JSON output. Copy failures remain visible without
claiming success. Tool start/end times and measured durations are stored with
trace events; completed durations survive refresh, and legacy records without
timing leave the duration blank. Approvals show command argv, paths, overwrite
and recursive options, configured task commands, and execution directories.
Approval applies only to that invocation.
`ChatSidebar`
creates, selects, and deletes persisted sessions and keeps the settings entry at the
bottom of the layout. Its `chatMachine` owns session
creation/loading/deletion, context history, agent runs, tool approval, retry,
cancellation, and errors. Selecting a session loads its persisted Context;
every later turn uses that Context and includes its `session_id` while calling
`/agent-runs`. Chat transitions through `creatingSession`, `loadingSession`,
`deletingSession`, `preparing`, `streaming`, `recovering`, `approvalRequired`,
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
Transport recovery only reads the existing run. A full retry after tools have
started requires confirmation because the original request can repeat effects.
Users can instead choose “仅重试回复”: the new request carries saved execution
records, supplies no tools, and allows zero tool rounds. This preserves existing
images/files without repeating their operations. The server's original request
and results remain available in history.

`tests/taskControl.browser.mjs` checks active refresh, explicit stop, retained
results after a provider failure, and both retry choices on desktop/mobile.
`tests/test_server_shutdown_process.py` sends a real SIGINT to an isolated local
server with a fake provider and temporary SQLite database, checking process exit,
provider closure, and persisted terminal/paused state.

`display_file` cards preview supported images and HTML snapshots, including older
HTML cards whose metadata predates `preview_kind: "html"`. HTML runs CSS and
JavaScript in a Blob-backed iframe with `sandbox="allow-scripts"`. HTTPS visual
resources are supported; data requests, forms and nested frames are blocked.
Local assets and chart data should be embedded in the HTML. The iframe cannot
access chat state, browser storage or login credentials. The original file remains
downloadable, and previews are disposed on identity changes or unmount.
`tests/fileDisplay.browser.mjs` checks interaction, HTTPS scripts/styles, isolation,
authenticated downloads, restored history, retries and cleanup at three widths.

Assistant text is rendered by `MarkdownContent` through `markdown-it`. Raw HTML
is disabled, unsafe link schemes are rejected, and external links receive
`noopener noreferrer`. Inline `$...$` / `\\(...\\)` and block `$$...$$` /
`\\[...\\]` formulas render with KaTeX using untrusted input mode; user messages
remain plain text.

Fenced code blocks show a language label, line numbers for multi-line code, a
wrap toggle and a copy button. Highlighting covers the common model languages
and their aliases; unknown languages fall back to escaped plain text.

A closed `mermaid` fence is drawn as a diagram, with a toggle back to its source.
Mermaid is loaded on first use, runs in strict mode with labels limited to text
formatting, and its links open in a new tab. A fence that is still streaming or
that Mermaid cannot parse stays a normal code block. Finished diagrams are kept
by source so later text deltas do not redraw them.

Visual tokens live in `src/styles/tokens.css` and are the single source for the
palette: neutral surfaces, a near-black action color, semantic status colors,
code and terminal colors, and no gradients. Pages do not redefine them. Native
`<select>` and `<details>` controls are restyled once in `src/styles/base.css`.
The image page uses the same sidebar shell as chat (`ImageSidebar`).

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

### Tool progress

Inline tool cards and run details share five phases: 准备、审批、执行中、完成、失败.
Cards show a short result preview, expandable arguments and full output, and
an error button that opens and focuses the corresponding failure details.
Inline and footer approval controls share the same decisions; only the active
run can accept approval actions.

After an SSE disconnect, the chat reads the original run snapshot and keeps
polling while it is running. Temporary network failures use increasing delays
(up to 10 seconds); stopping, switching sessions, or changing identity aborts
recovery. Snapshots restore interleaved text and tool progress without replaying
the execution request. Paused runs require an explicit action. This recovery
covers a connection loss while the chat remains open; reloading the page does
not automatically reattach to an active run.

`tests/toolProgress.browser.mjs` checks disconnect recovery, linked approvals,
error focus and layout at desktop and mobile widths with a mocked backend.


### Image tasks and the chat image tool

`/images.html` submits durable background tasks and polls saved status. Its task
list survives refresh, supports pagination and opens saved results. Upload edits
support multiple references and painting a PNG alpha mask on the first image.
Chat exposes `generate_image` through the existing tool catalog. Ask for an image
in a message, approve the tool call, and view/download the result in the tool card.
Follow-up messages can edit saved images by reference. Reopening a session restores
the cards and images; the composer has no separate image button or dialog.
Identity changes abort browser reads and clear image drafts and previews.

`pnpm run test:images:browser` covers existing image flows plus background refresh,
idempotent retry after a lost submission response, mask dimensions and alpha
pixels, and chat generation/edit/history on desktop and mobile. The browser
suite uses mocked API responses and never sends paid provider requests.


### Tool permissions

**设置 → 工具管理** lists every registered tool and its effective/default policy.
Users with `tools:configure` can save allow/ask/deny overrides or restore defaults.
The settings are stored per principal on the backend. Identity changes abort reads
and updates, and discard previews and feedback from the previous principal.
Successful changes refresh the workspace catalog so chat uses the updated tools.

`tests/toolPolicies.browser.mjs` checks save/retry, all three modes, default reset,
refresh persistence, chat catalog filtering, read-only access, and identity changes
during a pending update at desktop, mobile and narrow mobile widths.
