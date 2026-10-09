# Process sandbox

On Linux, set `runtime.sandbox_backend = "bubblewrap"` to run Shell, project tasks
and every built-in Git command through the same `SandboxExecuteProtocol` adapter.
Install Bubblewrap with support for `--disable-userns`, `--bind-fd`,
`--ro-bind-fd` and `--size`, and `prlimit` from util-linux.
User namespaces must be permitted by the host. Missing dependencies,
invalid mounts and execution failures never trigger a fallback to host execution.
The explicit `subprocess` backend remains available for trusted host execution.

## Workspace layout

Keep project files separate from the running service:

```text
EvernightAI/
  config.toml                    service configuration
  .evernight/runtime.sqlite3     service data and provider-key file
  .venv/                         read-only runtime dependencies
  workspaces/
    EvernightAI/                 independent project checkout and Git directory
```

Create an independent checkout, not a Git worktree referencing the service's
`.git` directory. For a local clone, use `git clone --no-hardlinks`. Never copy
the service configuration, `.env`, SQLite files or provider-key file into the
checkout. Workspace contents are intentionally available to the model's tools.

Example configuration, merged into your existing `config.toml`:

```toml
[runtime]
database_path = ".evernight/runtime.sqlite3"
sandbox_backend = "bubblewrap"

[runtime.sandbox]
workspace_root = "workspaces"
network_mode = "disabled"
include_python_environment = true
include_uv = true
include_node = false
readonly_paths = []
python_runtime_roots = []
protected_paths = []
timeout_seconds = 120.0
max_output_chars = 32000
memory_bytes = 2147483648
max_processes = 1024
cpu_seconds = 60
file_size_bytes = 67108864
temporary_storage_bytes = 1073741824

[tools.filesystem]
enabled = true
root = "workspaces"
allow_write = true

[tools.shell]
enabled = true
working_directory = "workspaces/EvernightAI"
allowed_commands = ["ls", "cat", "pwd", "git", "uv"]
is_need_approval = true

[tools.git]
enabled = true
repository_directory = "workspaces/EvernightAI"

[tools.project]
enabled = true
working_directory = "workspaces/EvernightAI"
commands = { tests = ["python", "-m", "pytest", "-m", "not sandbox", "tests"] }
```

Paths are relative to the service's startup directory. Enabled filesystem, Shell,
Git, project and download directories, including named projects, must stay inside
`workspace_root`. Named project directories still require absolute paths.
The workspace root is created if absent; create project directories before use.
The configured SQLite file, its provider-key file, `.evernight`, `.env`, the loaded
configuration file and additional `protected_paths` cannot overlap any workspace
or extra runtime mount. Invalid configuration fails before creating the database.
Read-only runtime sources must also stay outside `workspace_root`, preventing a
writable workspace alias from modifying the shared runtime.
File tools resolve paths and reject symlink escapes; process tools revalidate
mounts for every execution. The workspace directory is opened once per execution
and that same open directory is both validated and mounted, so replacing its
path afterwards cannot change what the command sees.

The chat sidebar can also open existing projects outside `workspace_root`. Add an
absolute backend-host directory under **工作文件夹 → 打开已有项目**. Added projects
persist in SQLite and are available in the project selector after restart. The
default configured directories above remain the fallback when no project is selected.
Files, Shell, Git and project tasks follow the selected directory for each request;
already-running and resumed requests retain their original selection. Only the
selected project is mounted at `/workspace` and its original absolute path.
The original path preserves existing console-script shebangs and editable package
references; both mounts expose the same selected files and use the same write mode.
Unregistered external directories,
service data and overlaps with read-only runtime paths remain forbidden.

## Runtime and execution

Each process sees its selected project directory at `/workspace`. `/usr`, `/bin`,
the system libraries and configured runtime paths are read-only. Only the selected
workspace allows persistent writes; temporary files use an isolated `/tmp`.
`/tmp` and `/dev/shm` are size-limited tmpfs mounts and the rest of `/dev` is
read-only. The sandbox hostname is always `sandbox`.
System alternatives (`/etc/alternatives`) and Fontconfig configuration
(`/etc/fonts`) are mounted read-only when present, so symlinked commands such as
`which` and `awk`, and font discovery, work normally. PATH includes the mounted
project Python environment, `/opt/evernight/bin`, and the standard system `bin` and `sbin`
directories. Use `uv` directly; `/opt/evernight/bin/uv` is its internal mount path.
The sandbox isolates process,
user, IPC and UTS namespaces, drops capabilities and prevents creating
nested user namespaces. Host Unix socket files, unselected home files, SSH credentials
and service environment variables are not exposed. The default
`network_mode = "disabled"` also isolates the network namespace.

The nearest `.venv` between the working directory and selected project root owns
Python execution. Its `bin` directory leads Python command lookup, and
`VIRTUAL_ENV` points to it. Its `pyvenv.cfg` selects the base Python installation,
which is mounted read-only. Existing uv installation aliases are preserved.
Standard `/usr` installations, the service user's uv Python store and explicitly
configured `python_runtime_roots` are approved sources. Additional roots approve
installations; they do not expose the whole store. Broken, escaping or unapproved
project environments fail explicitly instead of using a different interpreter.

`include_python_environment` provides the service Python environment as a
read-only fallback for projects without a `.venv`. It never replaces explicit
`.venv/bin/*` paths and does not set a service `VIRTUAL_ENV` on the project.
Arrays and shell scripts use the same filesystem paths and command lookup.
Project dependencies belong in the project's environment, which follows the
workspace write mode. The shared fallback stays read-only. Project imports use
normal Python behavior; set `PYTHONPATH` for custom layouts such as `docs_src`.
Local `node_modules/.bin` directories at the working directory and project root
are available on PATH.

`include_uv` mounts the installed uv binary read-only. uv follows the configured
network mode, its cache uses `/tmp`, and managed Python downloads are disabled.
To use installed dependencies without synchronizing the read-only environment:

```sh
uv run --no-sync python --version
```

If project tasks use Pyright or other Node programs, set `include_node = true`.
This mounts only the installed Node executable read-only at the fixed runtime
entrypoint; it does not expose the user's Node installation directory or cache.
Node must be installed before starting the service.

EvernightAI's OS isolation tests need to create their own user namespaces and
cannot run inside this sandbox. Use `python -m pytest -m 'not sandbox'` for its
project test task; run the complete suite from the host for sandbox integration
coverage. This marker does not exclude sandbox policy/schema unit tests.

Git read operations mount the repository read-only; staging, commits and branch
changes mount it read-write. Git hooks and configured helper commands execute
inside the same sandbox. Host global/system Git configuration is ignored; set
`user.name` and `user.email` in the workspace repository to create commits.
Network access is disabled by default even if an individual tool asks for it.
To enable networking for Shell, Git and project tasks, set
`runtime.sandbox.network_mode = "unrestricted"` and restart the service. This
shares the host network, including localhost. DNS configuration and HTTPS trust
stores are mounted read-only, and uv can download dependencies into a writable
project environment. The shared Python environment remains read-only. Git HTTP
remotes can connect; SSH credentials are still not mounted. Network allowlists
are unsupported and rejected during configuration validation.

Approvals and Shell literal-path rules still apply. Permission `allow` cannot
change mounts, override the configured network mode or increase resource ceilings.

## Resource limits

Limits apply inside the sandbox, before the requested program starts. Tool-specific
timeouts and output limits can be lower than runtime ceilings. Shell's configured
timeout is a default; a per-call override remains capped by the runtime ceiling.
Programs inherit
hard limits and cannot raise them. Timeout or cancellation terminates the process
group; destroying the PID namespace also terminates descendants that detach.
A timeout still fails the tool call, and the error detail carries the stdout and
stderr collected before the limit.
Output readers drain long lines in bounded chunks and retain bounded text/events.

| Setting | Enforcement |
| --- | --- |
| `timeout_seconds` | Wall-clock limit for the complete command and output draining |
| `max_output_chars` | Retained characters per stdout/stderr; combined event text also bounded |
| `memory_bytes` | `RLIMIT_AS`: virtual address space per process |
| `max_processes` | `RLIMIT_NPROC`: process/thread count for the real UID, including existing host tasks |
| `cpu_seconds` | `RLIMIT_CPU`: CPU time per process |
| `file_size_bytes` | `RLIMIT_FSIZE`: maximum size of each regular file |
| `temporary_storage_bytes` | tmpfs size of `/tmp` and of `/dev/shm`, each; this storage is host memory |

These are inherited process limits, not aggregate cgroup quotas for a task tree.
They do not cap total workspace disk use or total physical memory across all
children. Node/V8 may reserve substantial virtual address space; increase
`memory_bytes` deliberately for such tasks. Avoid a process ceiling below the
service user's existing thread count. Aggregate memory/PID/CPU and disk quotas
remain a separate cgroup/container integration.

The sandbox covers built-in process tools. Remote MCP services and operator-
configured MCP stdio servers are separate trusted integrations; they are not
launched through this adapter. HTTP/provider tools retain their existing explicit
network and permission policies.
