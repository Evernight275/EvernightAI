import asyncio
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from EvernightAI.core.protocol.shell import ShellSessionStoreProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.sandbox import SANDBOX_SIDE_CHANNEL_FD_ENV
from EvernightAI.core.schema.shell import ShellSessionState
from EvernightAI.infra.adapters.tool.shell_policy import (
    executable_name,
    inspected_commands,
    is_routine_command,
)

# Runs the model's script in the same shell that records where it ended up.
# The script cannot gain anything by writing to the channel itself: every
# recorded value is validated exactly like one the wrapper wrote.
SESSION_WRAPPER = (
    f'__evn_fd="${{{SANDBOX_SIDE_CHANNEL_FD_ENV}:-}}"\n'
    'if [ -n "$__evn_fd" ]; then\n'
    "  { printf 'S\\000'; env -0; } 2>/dev/null >\"/dev/fd/$__evn_fd\"\n"
    '  trap \'__evn_rc=$?; { printf "E\\000%s\\000" "$(pwd -P)"; env -0; }'
    ' 2>/dev/null >"/dev/fd/$__evn_fd"; exit "$__evn_rc"\' EXIT\n'
    "fi\n"
    "__evn_script=$1\n"
    "shift\n"
    'eval "$__evn_script"\n'
)
SANDBOX_ROOT = "/workspace"

# Values the shell manages itself or that only describe this one process.
_TRANSIENT_ENV = {"PWD", "OLDPWD", "SHLVL", "_", SANDBOX_SIDE_CHANNEL_FD_ENV}
# Values that change how every later command is loaded or interpreted.
_DENIED_ENV = {
    "BASH_ENV",
    "BASHOPTS",
    "CDPATH",
    "ENV",
    "GLOBIGNORE",
    "IFS",
    "PROMPT_COMMAND",
    "PS4",
    "SHELLOPTS",
}
_DENIED_ENV_PREFIXES = ("LD_", "DYLD_", "BASH_FUNC_")
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")


@dataclass(frozen=True)
class ShellSessionKey:
    owner_id: str | None
    key: str

    @property
    def scope(self) -> PrincipalScope | None:
        return PrincipalScope(owner_id=self.owner_id) if self.owner_id else None


@dataclass
class ShellSessionUpdate:
    state: ShellSessionState
    ignored: list[str] = field(default_factory=list)


def session_key(arguments: dict[str, Any]) -> ShellSessionKey | None:
    """Shell state follows the chat session, or the agent run without one."""
    context = arguments.get("_execution_context")
    if not isinstance(context, dict):
        return None
    owner_id = context.get("owner_id")
    owner = owner_id if isinstance(owner_id, str) and owner_id else None
    for kind in ("session_id", "run_id"):
        value = context.get(kind)
        if isinstance(value, str) and value:
            return ShellSessionKey(owner, f"{kind.removesuffix('_id')}:{value}")
    return None


class ShellSessionTracker:
    def __init__(
        self,
        store: ShellSessionStoreProtocol,
        *,
        allowed_env_keys: set[str] | None = None,
    ) -> None:
        self._store = store
        self._allowed_env_keys = allowed_env_keys
        self._locks: dict[ShellSessionKey, asyncio.Lock] = {}

    def lock(self, key: ShellSessionKey) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    def load(self, key: ShellSessionKey, root: Path) -> ShellSessionState:
        state = self._store.get(key.key, principal_scope=key.scope)
        if state is None or state.root != str(root):
            return ShellSessionState(
                session_key=key.key, owner_id=key.owner_id, root=str(root)
            )
        # Rules may have tightened since the state was recorded.
        state.env = {
            name: value
            for name, value in state.env.items()
            if self._env_rejection(name) is None
        }
        if "PATH" not in state.env:
            state.base_path = None
        return state

    def reset(self, key: ShellSessionKey) -> None:
        self._store.delete(key.key, principal_scope=key.scope)

    def save(self, key: ShellSessionKey, state: ShellSessionState) -> None:
        state.updated_at = datetime.now(timezone.utc)
        self._store.save(state, principal_scope=key.scope)

    def apply_capture(
        self, state: ShellSessionState, capture: str | None, root: Path
    ) -> ShellSessionUpdate:
        update = ShellSessionUpdate(state.model_copy(deep=True))
        parsed = parse_capture(capture)
        if parsed is None:
            if capture is not None:
                update.ignored.append("The shell state record was incomplete")
            return update
        start_env, cwd, end_env = parsed
        relative_cwd = sandbox_relative(cwd, root)
        if relative_cwd is None or not (root / relative_cwd).is_dir():
            update.ignored.append("cwd: the directory is outside the project root")
        else:
            update.state.cwd = relative_cwd
        for key in sorted(set(start_env) | set(end_env)):
            if key in _TRANSIENT_ENV or start_env.get(key) == end_env.get(key):
                continue
            reason = self._env_rejection(key)
            if reason is None and key == "PATH" and key in end_env:
                reason = self._apply_path(update.state, start_env, end_env[key], root)
                if reason is None:
                    continue
            if reason is not None:
                update.ignored.append(f"{key}: {reason}")
            elif key in end_env:
                update.state.env[key] = end_env[key]
            elif key in update.state.env:
                del update.state.env[key]
                if key == "PATH":
                    update.state.base_path = None
            else:
                update.ignored.append(f"{key}: inherited variables cannot be unset")
        return update

    def _env_rejection(self, key: str) -> str | None:
        if not _ENV_KEY.match(key):
            return "not a portable variable name"
        if key in _DENIED_ENV or key.startswith(_DENIED_ENV_PREFIXES):
            return "this variable changes how every later command runs"
        if self._allowed_env_keys is not None and key not in self._allowed_env_keys:
            return "outside the configured allowed_env_keys"
        return None

    def _apply_path(
        self,
        state: ShellSessionState,
        start_env: dict[str, str],
        value: str,
        root: Path,
    ) -> str | None:
        base = state.base_path
        if base is None:
            base = start_env.get("PATH", "").split(":")
        added = [entry for entry in value.split(":") if entry and entry not in base]
        if any(sandbox_relative(entry, root) is None for entry in added):
            return "PATH may only add directories inside the project root"
        if added:
            state.env["PATH"] = value
            state.base_path = base
        else:
            state.env.pop("PATH", None)
            state.base_path = None
        return None


def wrap_script(script: str) -> list[str]:
    return ["/bin/sh", "-c", SESSION_WRAPPER, "evernight-shell", script]


def parse_capture(
    capture: str | None,
) -> tuple[dict[str, str], str, dict[str, str]] | None:
    if not capture:
        return None
    records = capture.split("\0")
    if not records or records[0] != "S" or "E" not in records:
        return None
    end = records.index("E")
    if end + 1 >= len(records):
        return None
    return _env(records[1:end]), records[end + 1], _env(records[end + 2 :])


def sandbox_relative(path: str, root: Path) -> str | None:
    """A shell path as seen in the sandbox or on the host, relative to root."""
    candidate = PurePosixPath(path)
    if not candidate.is_absolute():
        return None
    if candidate == PurePosixPath(SANDBOX_ROOT) or PurePosixPath(SANDBOX_ROOT) in (
        candidate.parents
    ):
        relative = candidate.relative_to(SANDBOX_ROOT)
        if ".." in relative.parts:
            return None
        return relative.as_posix()
    try:
        return Path(os.path.realpath(path)).relative_to(root).as_posix()
    except ValueError:
        return None


def session_path_shadow_reason(
    state: ShellSessionState,
    command: list[str] | str,
    root: Path,
    *,
    relaxed: bool,
) -> str | None:
    """Commands the session PATH resolves to project files need approval."""
    path = state.env.get("PATH")
    if path is None or state.base_path is None:
        return None
    added = [
        root / relative
        for entry in path.split(":")
        if entry and entry not in state.base_path
        if (relative := sandbox_relative(entry, root)) is not None
    ]
    try:
        commands = inspected_commands(command, ignore_redirections=True)
    except (ValueError, RecursionError):
        commands = [command] if isinstance(command, list) else []
    for parts in commands:
        if not parts or "/" in parts[0] or "\\" in parts[0]:
            continue
        name = parts[0]
        if not any(_is_executable(directory / name) for directory in added):
            continue
        if relaxed and is_routine_command(parts):
            continue
        return (
            f"{executable_name(name)} resolves through a PATH entry this shell "
            "session added; approval is required"
        )
    return None


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _env(records: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for record in records:
        key, separator, value = record.partition("=")
        if separator and key:
            env[key] = value
    return env
