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
JSON-encoded argument arrays supplied as strings are normalized to arrays before
both authorization and execution. They follow the same literal-path, deletion
and blocked-command rules as ordinary arrays. `which` is a read-only query command.
Read-only `find` queries also run without additional approval. For `-exec` and
`-execdir`, the invoked command follows the same approval and blocked-command
rules, including quoted or escaped action terminators. File output and interactive
`find` actions require approval; discovered deletion targets remain forbidden.

On POSIX, tree-sitter-bash preserves pipelines, conditional chains, subshells,
redirections and stdin sources. Commands run without additional approval only
when their argument grammar is declared: unknown flags, extra positional
arguments, dynamic names, parse errors and unsupported syntax require approval.
For example, `uniq IN OUT` writes OUT, and `sort --compress-program=...` requires
approval because it can execute another program. Functions, control structures,
arithmetic, command/process substitution and unquoted heredocs remain opaque.
Nested scripts are inspected up to depth 16. PowerShell/cmd string scripts retain
the previous policy in this phase.

`allowed_commands` no longer trusts every argument of a named program. Bare
names and exact rules cannot extend the declared grammar. An explicit trailing
wildcard, such as `uv *`, trusts otherwise undeclared arguments and is a dangerous
opt-in: it can authorize arbitrary program execution even at `read_only`.
It does not override blocked rules, deletion checks, environment checks, opaque
syntax, known publishing/system effects or executable-source checks. Prefer
individual declared commands. Paths such as `./tool` and `bin/tool` always
require approval. Declared programs must resolve through the base PATH outside
the project; session-added directories never establish trust.

Set `is_need_approval = false` to use the following `approval_level` exemptions:

| Effect | read_only (default) | workspace_write | trusted_dev |
|---|---|---|---|
| Declared read operation | allow | allow | allow |
| Literal write target inside project root | ask | allow | allow |
| Network / project code (tests, builds, arbitrary project execution) | ask | ask | allow |
| Publish / system / unknown / opaque | ask | ask | ask |
| Delete with literal targets | ask | ask | ask |

Effects accumulate across all children. `trusted_dev` permits arbitrary project
code and requires the bubblewrap backend; configuration and assembly reject other
backends. Workspace writes resolve symlinks before execution and must stay inside
the root. This is best effort with subprocess: preflight cannot close TOCTOU races
or provide OS isolation. Use bubblewrap for execution-time containment.
`relaxed_approval` has been removed; old configuration fails with a migration
message. An explicit `ask` policy still asks for every call; `deny` blocks all calls.
Restart the service after changing configuration.

Ordinary commands can use environment variables, `export`, inline assignments,
`env`, and path expansion. The optional `env` argument sets string values for
that invocation only. The env argument, inline assignments, `env X=`, and
`export`/`set` share the same checks. `allowed_env_keys` is a hard limit for all
sources, including nested scripts. Dangerous keys (`LD_*`, `DYLD_*`, `PATH`,
`BASH_ENV`, `ENV`, `IFS`, `PYTHON*`, `NODE_OPTIONS`, `*_CONFIG_PATH`, `GIT_*`,
and other loader controls) require approval even in `trusted_dev`.
For invocations containing deletion, environment overrides and assignments are
forbidden, and deletion targets must be literal relative or absolute paths:
variables, home expansion and unquoted wildcards remain rejected after approval.
Command names must be literal so their operation can be inspected. Command/process
substitution and other unsupported computed syntax remain rejected. Bubblewrap
starts with a constructed environment and does not inherit service secrets.
The explicit `subprocess` backend inherits the host environment.

On POSIX, a quoted here-document such as `python - <<'PY'` may supply literal
standard input. The body is data rather than shell syntax: Python parentheses,
HTML tags and literal `$()` text do not become outer shell operations. Arbitrary
Python scripts still require approval, and approval shows the original complete
script. Input fed directly to a shell is also inspected as shell code. Blacklists
and commands after the closing delimiter remain checked.
Each here-document header must be one complete foreground command on a single
line, with no pipeline or command chain; output redirection is supported. Further
commands may follow the closing delimiter on subsequent lines. Unquoted
delimiters, here-strings, malformed delimiters and deletion invocations containing
here-documents remain forbidden even after approval.

Special characters in filenames must use the executing shell's literal syntax.
For POSIX, `rm './a$*.txt'`, `rm ./a\$\*.txt`, or the argument array
`["rm", "./a$*.txt"]` address one literal filename and require deletion approval.
`rm *.txt` and `rm "$HOME/a"` are rejected. Argument arrays bypass shell parsing;
their arguments are already literal and must not contain shell quoting added by
the caller. Windows filename rules do not permit literal `*` or `?`; quoting a
wildcard deletion target does not make it acceptable. CMD environment expansion
is forbidden for deletion even inside double quotes. PowerShell special-filename deletion
requires `-LiteralPath` as well as correct quoting.

Deletion using discovered/piped targets (`find -delete`, `xargs rm`) is rejected;
provide each target explicitly instead.
Explicit `blocked_commands` remain hard denials and are inspected in script
segments too. Inspection is conservative, not a proof of arbitrary program
behavior: code inside interpreters still requires review of the complete script.
Literal path checks do not constrain filesystem operations inside arbitrary
Python or other programs.

## Shell sessions

Each `restricted_shell` call still starts a new process, but calls that belong to
the same chat session (or, without one, the same agent run) share terminal state.
On POSIX, after a script string finishes, its final directory and exported
variables are recorded and applied to the next call, so `cd app`,
`export STAGE=dev` or `. .venv/bin/activate` carry over. Argument arrays use the
recorded state but do not change it. Aliases, functions, unexported variables and
background jobs do not carry over. State is stored per owner in SQLite and
survives a service restart. Calls without a session or run, such as direct tool
API calls, keep the old one-shot behavior.

Recorded state is validated before it is kept, whether the wrapper or the
script wrote it:

- The directory must stay inside the selected project root; otherwise the
  previous directory is kept. A recorded directory that has disappeared falls
  back to the root. The `cwd` argument is always relative to the root.
- `allowed_env_keys`, when configured, limits recorded variables too.
  Variables that change how every later command loads or runs (`LD_*`,
  `DYLD_*`, `BASH_ENV`, `ENV`, `IFS`, `CDPATH`, `PROMPT_COMMAND`, `SHELLOPTS`,
  `BASHOPTS`, exported functions) are never recorded. Inherited variables
  cannot be unset.
- `PATH` may only add directories inside the project root. A command name that
  then resolves to a file in such a directory requires approval, even if the
  name is trusted. Changing PATH requires approval; later calls using a recorded
  dangerous environment also require approval.

Approval is bound to the session cwd and an environment digest. If state changes
while approval is pending, use a new tool call to request approval again. Execution
rechecks the recorded state under the session lock. Digests and prompt content are
not logged. Pending bindings currently live in the shell tool instance; durable
approval binding across service restarts or multiple worker processes remains
follow-up work.

`cd` to a literal directory inside the root needs no approval; every command after it is inspected as before.
The result's `session` field reports the current directory, the recorded
variable names and anything that was ignored. Pass `reset_session: true` to
start again from the root with a clean environment.

## Background processes

When `[tools.shell] background_processes` is enabled (the default),
`shell_process_start` starts a long-running command such as a dev server,
watcher or REPL and returns a `process_id` immediately. It uses the same command
rules, approvals, sandbox and session directory/environment as
`restricted_shell`. `shell_process_read` returns new output (each call continues
where the previous read ended; `since` re-reads from an offset; `wait_seconds`
waits up to 30 seconds), `shell_process_write` sends stdin, `shell_process_stop`
stops the process and its children and `shell_process_list` shows the session's
processes. Writing to anything other than a trusted read-only command, such as
an interpreter, requires approval for each input.

Processes belong to their owner and session, are limited by
`max_background_processes` per owner, keep the most recent
`background_output_chars` of output, and are stopped after
`background_lifetime_seconds` and when the service stops. They are not
persisted: after a restart their ids are no longer found.

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

On POSIX, feeding a shell or interpreter through a pipe, input redirection or
heredoc requires approval, even in `trusted_dev`. Background stdin is exempt only
when the starting command was exempt and its declared `stdin_is_code` capability
is false; trusting a name or wildcard cannot grant stdin access to an interpreter.
Some valid but unmodeled forms, including multiple heredocs and login-shell
startup behavior, conservatively require approval.
