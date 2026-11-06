# CLAUDE.md

See @AGENTS.md — that file is the single source of truth for this project's
architecture rules, test expectations and design notes. Read it before changing
code, and make rule changes there, not here. This file only adds what AGENTS.md
does not cover.

## Environment

`AGENTS.md` writes its commands as PowerShell (`.\.venv\Scripts\python.exe`).
This checkout also runs under WSL2 / Linux, where the same venv exposes its
tools in `.venv/bin`:

```bash
.venv/bin/python -m pytest          # normal test suite
.venv/bin/pyright                   # type checking
```

Start the local HTTP interface (environment-variable factory):

```bash
EVERNIGHTAI_DATABASE_PATH=".evernight/runtime.sqlite3" \
EVERNIGHTAI_FILESYSTEM_ROOT="$PWD" \
.venv/bin/python -m uvicorn EvernightAI.bootstrap.http:create_app --factory --reload
```

Start from `config.toml` instead (all configured tools, MCP sources, sandbox,
authentication):

```bash
EVERNIGHTAI_CONFIG_PATH="config.toml" \
.venv/bin/python -m uvicorn EvernightAI.bootstrap.http:create_app_from_config_path --factory --reload
```

The real-provider smoke tests in `AGENTS.md` translate the same way: set the
same variables as `NAME=value` prefixes and call `.venv/bin/python -m pytest`.
They stay opt-in — do not run them unless asked.
