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
categories, tool preflight checks, configured filesystem roots, command restrictions,
and network restrictions still apply. A server-blocked tool appears as forbidden
in management and cannot be enabled by a user override. Tool permission categories
such as `write` and `external_api` describe operations; API permissions govern
access to management endpoints and Agent operations.

## Shell commands

`restricted_shell` accepts either a process argument array or a shell script string:

```json
{"command": "ls | head -n 5 && pwd"}
```

Strings execute using `/bin/sh -c` on POSIX or `cmd.exe /d /s /c` on Windows.
Arrays keep their arguments literal. Pipes, redirection and command chains are
available in script mode; the full script appears in approval and terminal cards,
including after a page refresh.

Common read commands can run without additional approval. `allowed_commands`
identifies trusted commands rather than an exhaustive executable allowlist.
Commands outside that list require approval instead of automatic rejection.
Deletion, file changes, network/system operations, interpreters, command wrappers,
redirection and complex scripts also require approval,
even when the tool's configured mode is `allow`. An `ask` policy still asks for
every call; a `deny` policy blocks every call.

To reduce command approvals, set `[tools.shell]` to `is_need_approval = false`
and `relaxed_approval = true`. Routine file copying, moving, directory creation,
redirection, HTTP downloads, Git status/add/commit/fetch/pull/push/clone, dependency
installation, tests and builds then run without additional approval. Inspected
shell chains and uv wrappers use the same rules for their nested commands.
Deletion commands still require approval; wildcard and discovered deletion targets
remain forbidden, and configured blocked commands still win. Arbitrary interpreter
scripts, unfamiliar commands, package removal and Git clean/reset/rm retain
approval. Explicit per-user `ask` and `deny` settings still apply. Restart the
service after changing configuration.

Paths must be literal relative or absolute paths. Shell variable expansion,
command/process substitution, home-directory expansion and unquoted wildcards
are rejected even after approval. Environment overrides through `env`, inline
assignments and environment-setting commands are forbidden. Bubblewrap supplies
a fixed runtime environment; it does not inherit service secrets. The explicit
`subprocess` backend inherits the host environment.

Special characters in filenames must use the executing shell's literal syntax.
For POSIX, `rm './a$*.txt'`, `rm ./a\$\*.txt`, or the argument array
`["rm", "./a$*.txt"]` address one literal filename and require deletion approval.
`rm *.txt` and `rm "$HOME/a"` are rejected. Argument arrays bypass shell parsing;
their arguments are already literal and must not contain shell quoting added by
the caller. Windows filename rules do not permit literal `*` or `?`; quoting a
wildcard deletion target does not make it acceptable. CMD environment expansion
is forbidden even inside double quotes. PowerShell special-filename deletion
requires `-LiteralPath` as well as correct quoting.

Deletion using discovered/piped targets (`find -delete`, `xargs rm`) is rejected;
provide each target explicitly instead.
Explicit `blocked_commands` remain hard denials and are inspected in script
segments too. Inspection is conservative, not a proof of arbitrary program
behavior: code inside interpreters still requires review of the complete script.
Literal path checks do not constrain filesystem operations inside arbitrary
Python or other programs.

Working-directory validation, timeouts and output limits
remain in effect. The `subprocess` backend runs as the host user and does not
isolate filesystem access; use the `bubblewrap` backend when OS isolation is
needed. On POSIX, timeout and cancellation kill the command's process group.
See [process sandbox configuration](sandbox.md) for isolated workspaces, read-only
Python/uv mounts, Git execution and resource limits.

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
