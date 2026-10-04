# Tool Permissions

Open **Settings → 工具管理** in chat or on the standalone settings page.
Each registered tool has three choices:

| Mode | Behavior |
| --- | --- |
| 允许 (`allow`) | Execute without per-call approval |
| 每次询问 (`ask`) | Pause until the user approves the call |
| 禁止 (`deny`) | Remove from the available catalog and reject execution |

**恢复默认** removes the override and follows the tool's registration and server
safety policy. Explicit overrides survive refresh, SQLite restarts, and tool-source
refreshes. They apply to subsequent calls, including calls pending approval; they
do not cancel operations already running.

With authentication enabled, settings belong to the authenticated principal.
Different API keys for the same principal share settings; other principals keep
their own settings. Without authentication, the local workspace shares anonymous
settings. Reading requires `tools:list`; changing or resetting requires
`tools:configure` (or `*`). A read-only user can inspect settings without editing.

The server checks the latest stored policy for every tool execution and refreshes
the available definitions before each Agent model round. Browser selections and
client-supplied definitions cannot override stored denial. The Agent ignores
approval fields supplied by model-returned calls and uses explicit request/resume
approval decisions. A denied or expired decision prevents execution even if the
tool's policy later becomes `allow`.

Allowing a tool only changes approval behavior. The server's blocked permission
categories, tool preflight checks, configured filesystem roots, command allowlists,
and network restrictions still apply. A server-blocked tool appears as forbidden
in management and cannot be enabled by a user override. Tool permission categories
such as `write` and `external_api` describe operations; API permissions govern
access to management endpoints and Agent operations.

## HTTP API

| Endpoint | Permission | Result |
| --- | --- | --- |
| `GET /tools` | `tools:list` | Current principal's available tool definitions |
| `GET /tools/policies` | `tools:list` | All registered tools, including forbidden tools, and policy summaries |
| `PUT /tools/{tool_name}/policy` | `tools:configure` | Save `{ "mode": "allow" \| "ask" \| "deny" }` |
| `DELETE /tools/{tool_name}/policy` | `tools:configure` | Remove the override and return the restored summary |

Policy responses include `tool`, effective `mode`, `default_mode`, optional
`configured_mode`, and optional `blocked_reason`. A missing `configured_mode`
means registration/server defaults apply. These responses use `Cache-Control:
no-store`. Unknown tools return 404; invalid modes return 400. Requests cannot
select another principal's policy.

SQLite migration 8 adds `tool_policies`, keyed by principal and registered tool
name. Memory runtimes keep settings only for their lifetime. Source-managed names,
including MCP namespaces, retain their overrides when definitions are refreshed.

`BasicToolSafetyPolicy` treats `None` as the default permission set and an explicit
empty set as empty. Custom composition can therefore clear the blocked or
approval-required categories without accidentally restoring defaults.
