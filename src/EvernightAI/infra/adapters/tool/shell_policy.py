import os
import re
import shlex
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from EvernightAI.core.schema.shell import ShellSessionState
from EvernightAI.infra.adapters.tool.shell_heredocs import (
    ShellScript,
    parse_quoted_heredocs,
)
from EvernightAI.infra.adapters.tool.shell_literals import (
    ShellDialect,
    literal_script_reason,
)
from EvernightAI.infra.adapters.tool.shell_specs import (
    SPECS,
    STDIN_CODE,
    STDIN_SPECS,
    SYSTEM_COMMANDS,
    Effect,
    arguments,
)
from EvernightAI.infra.adapters.tool.shell_syntax import Syntax, parse_script

READ_COMMANDS = {
    # Changing directory runs nothing; every later command is still inspected.
    "cd",
    "cat",
    "cut",
    "echo",
    "grep",
    "head",
    "ls",
    "pwd",
    "rg",
    "sort",
    "tail",
    "uniq",
    "wc",
    "whoami",
    "which",
}
DELETE_COMMANDS = {
    "rm",
    "rmdir",
    "unlink",
    "shred",
    "del",
    "erase",
    "remove-item",
    "ri",
}
SCRIPT_COMMANDS = {
    "bash",
    "sh",
    "dash",
    "zsh",
    "fish",
    "cmd",
    "powershell",
    "pwsh",
    "python",
    "python3",
    "node",
    "perl",
    "ruby",
}
WRITE_COMMANDS = {
    "cp",
    "mv",
    "tee",
    "touch",
    "mkdir",
    "chmod",
    "chown",
    "truncate",
    "dd",
    "sed",
    "awk",
    "curl",
    "wget",
    "git",
    "npm",
    "pnpm",
    "pip",
    "pip3",
    "apt",
    "apt-get",
    "dnf",
    "yum",
    "systemctl",
    "kill",
    "pkill",
}
WRAPPERS = {"sudo", "env", "command", "exec", "nohup", "nice", "xargs"}
SHELL_COMMANDS = {"bash", "sh", "dash", "zsh", "fish", "cmd", "powershell", "pwsh"}
FIND_EXEC_ACTIONS = {"-exec", "-execdir", "-ok", "-okdir"}
SHELL_SCRIPT_FLAGS = {"-c", "-lc", "-command", "/c", "--command"}


def executable_name(value: str) -> str:
    return PureWindowsPath(value).name.lower().removesuffix(".exe")


def _shell_tokens(script: str) -> list[tuple[str, bool]]:
    operators = ";|&<>()"
    replacements = {char: f"\x00{index}" for index, char in enumerate(operators)}
    protected: list[str] = []
    quote: str | None = None
    escaped = False
    for char in script:
        if escaped:
            protected.append(replacements.get(char, char))
            escaped = False
            continue
        if char == "\\" and quote != "'":
            protected.append(char)
            escaped = True
            continue
        if char in {"'", '"'} and (quote is None or quote == char):
            quote = None if quote is not None else char
        protected.append(replacements.get(char, char) if quote else char)
    lexer = shlex.shlex("".join(protected), posix=True, punctuation_chars=operators)
    lexer.whitespace_split = True
    lexer.commenters = ""
    result = []
    for token in lexer:
        is_operator = bool(token) and all(char in operators for char in token)
        for char, replacement in replacements.items():
            token = token.replace(replacement, char)
        result.append((token, is_operator))
    return result


def shell_commands(
    script: str, *, ignore_redirections: bool = False
) -> list[list[str]]:
    script = parse_quoted_heredocs(script).text
    script = re.sub(r"\\\r?\n", "", script).replace("\n", " ; ")
    commands: list[list[str]] = []
    current: list[str] = []
    redirection_target = False
    for token, is_operator in _shell_tokens(script):
        if redirection_target:
            redirection_target = False
            continue
        if (
            is_operator
            and ignore_redirections
            and token in {"<", ">", ">>", "<&", ">&", "&>", "&>>"}
        ):
            redirection_target = True
            continue
        if is_operator:
            if current:
                commands.append(current)
                current = []
        else:
            current.append(token)
    if current:
        commands.append(current)
    return commands


def _find_execution_commands(parts: list[str]) -> list[list[str]] | None:
    commands: list[list[str]] = []
    index = 1
    while index < len(parts):
        if parts[index] not in FIND_EXEC_ACTIONS:
            index += 1
            continue
        start = index + 1
        index = start
        while index < len(parts):
            if parts[index] == ";" or (
                parts[index] == "+" and index > start and parts[index - 1] == "{}"
            ):
                break
            index += 1
        if index == start or index == len(parts):
            return None
        commands.append(parts[start:index])
        index += 1
    return commands


def unwrap_command(command: list[str]) -> list[str]:
    while command and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", command[0]):
        command = command[1:]
    while command and executable_name(command[0]) in WRAPPERS:
        if (
            executable_name(command[0]) == "command"
            and len(command) > 1
            and command[1] in {"-v", "-V"}
        ):
            return []
        wrapper = executable_name(command[0])
        valued_options = {
            "sudo": {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt"},
            "env": {"-u", "--unset", "-C", "--chdir"},
            "nice": {"-n", "--adjustment"},
        }.get(wrapper, set())
        command = command[1:]
        while command and (command[0].startswith("-") or "=" in command[0]):
            option = command[0]
            command = command[2:] if option in valued_options else command[1:]
    return command


def inspected_commands(
    command: list[str] | str, *, ignore_redirections: bool = False
) -> list[list[str]]:
    if isinstance(command, str):
        parsed = parse_quoted_heredocs(command)
        commands = shell_commands(parsed.text, ignore_redirections=ignore_redirections)
    else:
        parsed = None
        commands = [command]
    result: list[list[str]] = []
    for parts in commands:
        if parts:
            result.append(parts)
        parts = unwrap_command(parts)
        if not parts:
            continue
        if parts not in result:
            result.append(parts)
        if executable_name(parts[0]) == "find":
            for nested in _find_execution_commands(parts) or []:
                result.extend(
                    inspected_commands(nested, ignore_redirections=ignore_redirections)
                )
        if executable_name(parts[0]) in SHELL_COMMANDS:
            for index, part in enumerate(parts[1:], start=1):
                if part.lower() in {"-c", "-lc", "-command", "/c", "--command"}:
                    if index + 1 < len(parts):
                        result.extend(
                            inspected_commands(
                                parts[index + 1],
                                ignore_redirections=ignore_redirections,
                            )
                        )
                    break
    if parsed is not None:
        for body in _shell_heredoc_bodies(parsed):
            result.extend(
                inspected_commands(body, ignore_redirections=ignore_redirections)
            )
    return result


def _shell_heredoc_bodies(parsed: ShellScript) -> list[str]:
    result: list[str] = []
    for document in parsed.here_documents:
        for parts in inspected_commands(document.header, ignore_redirections=True):
            if executable_name(parts[0]) in SHELL_COMMANDS:
                result.append(document.body)
                break
            if executable_name(parts[0]) in {"uv", "busybox"} and any(
                executable_name(part) in SHELL_COMMANDS for part in parts[1:]
            ):
                result.append(document.body)
                break
    return result


def contains_deletion(command: list[str] | str, *, depth: int = 0) -> bool:
    if depth > 16:
        return True
    try:
        commands = inspected_commands(command, ignore_redirections=True)
    except (ValueError, RecursionError):
        return True
    for parts in commands:
        name = executable_name(parts[0])
        if name in DELETE_COMMANDS:
            return True
        if name == "command" and len(parts) > 1 and parts[1] in {"-v", "-V"}:
            continue
        if name in {"uv", "busybox", "find", "xargs"} and (
            "-delete" in parts
            or any(executable_name(part) in DELETE_COMMANDS for part in parts[1:])
        ):
            return True
        if name not in SHELL_COMMANDS | WRAPPERS | {"uv", "find", "busybox"}:
            continue
        for index, part in enumerate(parts):
            if executable_name(part) not in SHELL_COMMANDS:
                continue
            for flag_index in range(index + 1, len(parts) - 1):
                if parts[flag_index].lower() in {
                    "-c",
                    "-lc",
                    "-command",
                    "/c",
                    "--command",
                }:
                    if contains_deletion(parts[flag_index + 1], depth=depth + 1):
                        return True
                    break
    return False


def opaque_command_reason(
    command: list[str] | str, *, dialect: ShellDialect | None = None, depth: int = 0
) -> str | None:
    """Why a command hides what it runs from inspection, if it does."""
    dialect = dialect or _default_dialect()
    if depth > 16:
        return "Nested shell commands exceed the inspection limit; approval is required"
    if isinstance(command, str):
        reason = literal_script_reason(command, dialect, strict_paths=False)
        if reason is not None:
            return reason
    try:
        commands = inspected_commands(command, ignore_redirections=True)
    except (ValueError, RecursionError):
        return "Shell syntax could not be inspected; approval is required"
    if isinstance(command, str) and any(
        _dynamic_name(parts[0], dialect) for parts in commands
    ):
        return "Dynamic command names require approval"
    nested = [script for parts in commands for script in _shell_scripts(parts)]
    if isinstance(command, str) and dialect == "posix":
        nested.extend(
            (body, "posix")
            for body in _shell_heredoc_bodies(parse_quoted_heredocs(command))
        )
    for script, nested_dialect in nested:
        reason = opaque_command_reason(script, dialect=nested_dialect, depth=depth + 1)
        if reason is not None:
            return reason
    return None


def may_delete(
    command: list[str] | str, *, dialect: ShellDialect | None = None
) -> bool:
    """Deletion is visible, or named anywhere in a command that hides what it runs."""
    try:
        inspected_commands(command, ignore_redirections=True)
    except (ValueError, RecursionError):
        return _mentions_deletion(command)
    return contains_deletion(command) or (
        opaque_command_reason(command, dialect=dialect) is not None
        and _mentions_deletion(command)
    )


def mentions_command(command: list[str] | str, rules: list[list[str]]) -> bool:
    """Whether the raw command text names any rule as a sequence of words."""
    text = command if isinstance(command, str) else " ".join(command)
    return any(
        rule
        and re.search(
            r"(?<![\w.-])"
            + r"\s+".join(re.escape(part) for part in rule)
            + r"(?![\w-])",
            text,
            re.IGNORECASE,
        )
        for rule in rules
    )


def _mentions_deletion(command: list[str] | str) -> bool:
    return mentions_command(
        command, [[name] for name in sorted(DELETE_COMMANDS)] + [["-delete"]]
    )


def _default_dialect() -> ShellDialect:
    return "cmd" if os.name == "nt" else "posix"


def _dynamic_name(name: str, dialect: ShellDialect) -> bool:
    return bool(
        ("$" in name or dialect == "cmd" and re.search(r"%[^%]+%|![^!]+!", name))
        and not re.match(r"^(?:\$(?:env:)?)?[A-Za-z_][A-Za-z_0-9]*=", name)
    )


def _shell_scripts(parts: list[str]) -> list[tuple[str, ShellDialect]]:
    """Scripts passed to shells with -c and similar flags."""
    if executable_name(parts[0]) not in SHELL_COMMANDS | WRAPPERS | {
        "uv",
        "find",
        "busybox",
    }:
        return []
    scripts: list[tuple[str, ShellDialect]] = []
    for index, part in enumerate(parts):
        shell = executable_name(part)
        if shell not in SHELL_COMMANDS:
            continue
        for flag_index in range(index + 1, len(parts) - 1):
            if parts[flag_index].lower() in SHELL_SCRIPT_FLAGS:
                scripts.append(
                    (
                        parts[flag_index + 1],
                        "cmd"
                        if shell == "cmd"
                        else "powershell"
                        if shell in {"powershell", "pwsh"}
                        else "posix",
                    )
                )
                break
    return scripts


def literal_command_reason(
    command: list[str] | str, *, dialect: ShellDialect | None = None, depth: int = 0
) -> str | None:
    """Why a deleting command is rejected outright; other commands pass."""
    dialect = dialect or _default_dialect()
    if depth > 16:
        return "Nested shell commands exceed the inspection limit"
    if not may_delete(command, dialect=dialect):
        return None
    if isinstance(command, str):
        reason = literal_script_reason(command, dialect)
        if reason is not None:
            return reason
    try:
        commands = inspected_commands(command, ignore_redirections=True)
    except (ValueError, RecursionError):
        return "Shell syntax could not be inspected"
    for parts in commands:
        name = executable_name(parts[0])
        if isinstance(command, str) and _dynamic_name(parts[0], dialect):
            return (
                "Command names must be literal so deletion operations can be inspected"
            )
        if name in WRAPPERS and any(
            re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", part) for part in parts[1:]
        ):
            return "Environment variable assignments and overrides are forbidden"
        if name in {"find", "xargs"} and (
            "-delete" in parts
            or any(executable_name(part) in DELETE_COMMANDS for part in parts[1:])
            or name == "find"
            and any(
                contains_deletion(nested)
                for nested in _find_execution_commands(parts) or []
            )
        ):
            return "Deletion requires explicit literal paths, not discovered or piped targets"
        if name in DELETE_COMMANDS:
            targets = (
                parts[parts.index("--") + 1 :]
                if "--" in parts
                else [part for part in parts[1:] if not part.startswith("-")]
            )
            if not any(targets):
                return "Deletion requires an explicit relative or absolute path"
        if name in DELETE_COMMANDS and any(not part for part in parts[1:]):
            return "Deletion paths must not be empty"
        if name in {"env", "export", "set", "setenv", "unset"} or re.match(
            r"^[A-Za-z_][A-Za-z_0-9]*=", parts[0]
        ):
            return "Environment variable assignments and overrides are forbidden"
        if (
            dialect == "cmd"
            and name in DELETE_COMMANDS
            and any("*" in part or "?" in part for part in parts[1:])
        ):
            return "Windows deletion requires literal paths; wildcard targets are forbidden"
        if (
            name in {"remove-item", "ri"}
            and any("*" in part or "?" in part for part in parts[1:])
            and "-literalpath" not in [part.lower() for part in parts[1:]]
        ):
            return "PowerShell deletion of special filenames requires -LiteralPath"
        for script, nested_dialect in _shell_scripts(parts):
            reason = literal_command_reason(
                script, dialect=nested_dialect, depth=depth + 1
            )
            if reason is not None:
                return reason
    return None


def _legacy_approval_reason(
    command: list[str] | str, trusted_commands: set[str], *, relaxed: bool = False
) -> str | None:
    reason = opaque_command_reason(command)
    if reason is not None:
        return reason
    if isinstance(command, str):
        try:
            script = parse_quoted_heredocs(command).text
            if any(
                token == "&" and is_operator
                for token, is_operator in _shell_tokens(script)
            ):
                return "Background commands require approval"
        except ValueError:
            return "Shell syntax could not be inspected; approval is required"
        if not relaxed and any(char in command for char in "<>\n"):
            return "Shell redirection or multiline scripts require approval"
        try:
            commands = shell_commands(command)
        except ValueError:
            return "Shell syntax could not be inspected; approval is required"
    else:
        commands = [command]
    if relaxed:
        commands = inspected_commands(command, ignore_redirections=True)
    for parts in commands:
        if not parts:
            continue
        name = executable_name(parts[0])
        if name in DELETE_COMMANDS:
            return "Deleting files requires approval"
        if name == "find":
            if any(
                part
                in {
                    "-delete",
                    "-fprint",
                    "-fprint0",
                    "-fprintf",
                    "-fls",
                    "-ok",
                    "-okdir",
                }
                for part in parts[1:]
            ):
                return "Writing or interactive find actions require approval"
            nested_commands = _find_execution_commands(parts)
            if nested_commands is None:
                return "find execution actions could not be inspected; approval is required"
            for nested in nested_commands:
                reason = _legacy_approval_reason(
                    nested, trusted_commands, relaxed=relaxed
                )
                if reason is not None:
                    return reason
            continue
        if relaxed and _routine_command(parts):
            continue
        if name in WRITE_COMMANDS:
            return "File changes, network access or system operations require approval"
        if name in WRAPPERS or name in SCRIPT_COMMANDS:
            if len(parts) == 2 and parts[1] in {"--version", "-V"}:
                continue
            return "Interpreters and command wrappers require approval"
        if name in READ_COMMANDS and parts[0] == name:
            if name == "sort" and any(
                part.startswith("--output")
                or (part.startswith("-") and not part.startswith("--") and "o" in part)
                for part in parts[1:]
            ):
                return "Writing sorted output to a file requires approval"
            if name == "rg" and any(
                part.startswith(("--pre", "--hostname-bin")) for part in parts[1:]
            ):
                return "External search preprocessors require approval"
            continue
        if parts[0] in trusted_commands:
            if name == "uv" and parts[1:] not in [["--version"], ["version"]]:
                return "Package management and program execution require approval"
            continue
        if any(_exact_rule(rule, parts) for rule in trusted_commands):
            continue
        return "Commands outside the trusted list require approval"
    return None


def _routine_command(parts: list[str]) -> bool:
    name = executable_name(parts[0])
    args = parts[1:]
    if name in {"export", "unset", "set", "setenv"}:
        return True
    if re.match(r"^\$(?:env:)?[A-Za-z_][A-Za-z_0-9]*=", parts[0]):
        return True
    if re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", parts[0]) or name == "env":
        nested = unwrap_command(parts)
        return (
            not nested or _legacy_approval_reason(nested, set(), relaxed=True) is None
        )
    if name == "command" and args and args[0] in {"-v", "-V"}:
        return True
    if name in {"cp", "mv", "tee", "touch", "mkdir", "curl", "wget", "sort"}:
        return True
    if name in {
        "pytest",
        "pyright",
        "ruff",
        "mypy",
        "tsc",
        "vitest",
        "eslint",
        "prettier",
    }:
        return True
    if name in {"python", "python3"}:
        if len(args) >= 2 and args[:2] == ["-m", "pip"]:
            return _routine_command(["pip", *args[2:]])
        return (
            len(args) >= 2
            and args[0] == "-m"
            and args[1] in {"pytest", "pyright", "ruff", "mypy", "compileall"}
        )
    if name in {"pip", "pip3"}:
        return bool(args) and args[0] in {
            "install",
            "download",
            "list",
            "show",
            "freeze",
            "check",
        }
    if name == "git":
        return bool(args) and args[0] in {
            "status",
            "diff",
            "log",
            "show",
            "ls-files",
            "rev-parse",
            "add",
            "commit",
            "fetch",
            "pull",
            "push",
            "clone",
        }
    if name in {"npm", "pnpm", "yarn"}:
        if len(args) >= 2 and args[0] == "exec":
            return _routine_command(args[1:])
        return bool(args) and (
            args[0] in {"install", "i", "ci", "test", "build", "lint", "typecheck"}
            or len(args) >= 2
            and args[0] == "run"
            and args[1] in {"test", "build", "lint", "typecheck", "dev", "start"}
        )
    if name == "uv" and args:
        if args[0] in {
            "sync",
            "lock",
            "add",
            "export",
            "tree",
            "venv",
            "version",
            "--version",
        }:
            return True
        if args[0] == "pip":
            return _routine_command(["pip", *args[1:]])
        if args[0] == "run":
            nested = args[1:]
            while nested and nested[0] in {
                "--active",
                "--no-sync",
                "--no-project",
                "--frozen",
                "--locked",
                "--",
            }:
                nested = nested[1:]
            return (
                bool(nested)
                and _legacy_approval_reason(nested, set(), relaxed=True) is None
            )
    if name in SHELL_COMMANDS:
        return (
            len(args) >= 2
            and args[0].lower() in {"-c", "-lc", "-command", "/c", "--command"}
            and _legacy_approval_reason(args[1], set(), relaxed=True) is None
        )
    return False


def _exact_rule(rule: str, command: list[str]) -> bool:
    try:
        return shlex.split(rule) == command
    except ValueError:
        return False


# POSIX policy uses the syntax tree; the functions above retain Windows behavior.


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str | None = None
    stdin_is_code: bool = True
    effects: frozenset[Effect] = frozenset()


def dangerous_env_key(key: str) -> bool:
    key = key.upper()
    return (
        key
        in {
            "PATH",
            "BASH_ENV",
            "ENV",
            "IFS",
            "NODE_OPTIONS",
            "CDPATH",
            "SHELLOPTS",
            "BASHOPTS",
            "GLOBIGNORE",
            "PROMPT_COMMAND",
            "PS4",
            "RUBYOPT",
            "PERL5OPT",
            "ZDOTDIR",
            "HOME",
            "XDG_CONFIG_HOME",
            "SHELL",
            "PAGER",
            "EDITOR",
            "VISUAL",
            "LESSOPEN",
            "LESSCLOSE",
            "PERL5LIB",
            "RUBYLIB",
            "BASH_LOADABLES_PATH",
        }
        or key.startswith(
            (
                "LD_",
                "DYLD_",
                "PYTHON",
                "GIT_",
                "BASH_FUNC_",
                "NPM_CONFIG_",
                "CARGO_",
                "RUSTC_",
            )
        )
        or key.endswith("_CONFIG_PATH")
    )


class ShellCommandPolicy:
    def __init__(
        self,
        *,
        level: str = "read_only",
        trusted_commands: set[str] | None = None,
        blocked_commands: set[str] | None = None,
        root: Path,
        dialect: ShellDialect | None = None,
        allowed_env_keys: set[str] | None = None,
        cwd: Path | None = None,
    ) -> None:
        if level not in {"read_only", "workspace_write", "trusted_dev"}:
            raise ValueError("Unknown shell approval_level")
        self.level = level
        self.trusted = trusted_commands or set()
        self.blocked = blocked_commands or set()
        self.root = root.resolve()
        self.cwd = cwd or self.root
        self.dialect: ShellDialect = dialect or _default_dialect()
        self.allowed_env_keys = allowed_env_keys

    def commands(self, command: str | list[str], *, depth: int = 0) -> list[list[str]]:
        if depth > 16:
            return []
        if self.dialect != "posix":
            return inspected_commands(command, ignore_redirections=True)
        result: list[list[str]] = []
        tree = parse_script(command)
        for body in tree.shell_bodies():
            result.extend(self.commands(body, depth=depth + 1))
        for item in tree.commands():
            parts = [w.literal if w.literal is not None else w.raw for w in item.argv]
            if not parts:
                continue
            result.append(parts)
            nested = self._nested(parts)
            if nested is not None:
                result.extend(self.commands(nested, depth=depth + 1))
        # Legacy discovery is retained only as an additional deny-side scanner.
        # It never grants permission and also finds commands in opaque wrappers.
        try:
            for parts in inspected_commands(command, ignore_redirections=True):
                if parts not in result:
                    result.append(parts)
        except (ValueError, RecursionError):
            pass
        return result

    def _nested(self, parts: list[str]) -> str | list[str] | None:
        if (
            executable_name(parts[0]) in {"sh", "bash", "dash", "zsh"}
            and len(parts) >= 3
            and parts[1] in {"-c", "-lc"}
        ):
            return parts[2]
        if parts[0] in {"env", "command", "exec", "nohup", "nice", "xargs"}:
            nested = unwrap_command(parts)
            return nested if nested != parts and nested else None
        if parts[:2] == ["uv", "run"]:
            index = 2
            while index < len(parts) and parts[index] in {
                "--active",
                "--no-sync",
                "--no-project",
                "--frozen",
                "--locked",
                "--",
            }:
                index += 1
            return parts[index:] or None
        return None

    def evaluate(
        self,
        command: str | list[str],
        env: dict[str, str] | None = None,
        session_state: ShellSessionState | None = None,
        *,
        depth: int = 0,
    ) -> Decision:
        if depth > 16:
            return Decision("ask", "Nested shell commands exceed the inspection limit")
        env = env or {}
        syntax = parse_script(command) if self.dialect == "posix" else None
        deletion_text = command
        if isinstance(command, str) and self.dialect == "posix":
            try:
                deletion_text = parse_quoted_heredocs(command).text
            except ValueError:
                pass
        if (
            syntax is not None
            and syntax.reasons()
            and _mentions_deletion(deletion_text)
        ):
            return Decision(
                "reject", "Opaque deletion cannot guarantee explicit literal paths"
            )
        try:
            reason = literal_command_reason(command, dialect=self.dialect)
        except RecursionError:
            return Decision("reject", "Shell nesting exceeds the inspection limit")
        if reason:
            return Decision("reject", reason)
        rules = [shlex.split(rule) for rule in self.blocked]
        commands = self.commands(command, depth=depth)
        if any(
            parts[: len(rule)] == rule for parts in commands for rule in rules if rule
        ) or (
            (
                syntax is not None
                and bool(syntax.reasons())
                or opaque_command_reason(command, dialect=self.dialect) is not None
            )
            and mentions_command(command, rules)
        ):
            return Decision(
                "reject", "The command is blocked by a configured command rule"
            )
        if self.allowed_env_keys is not None and not set(env).issubset(
            self.allowed_env_keys
        ):
            return Decision(
                "reject", "Environment keys are outside the configured allowed_env_keys"
            )
        if env and may_delete(command, dialect=self.dialect):
            return Decision(
                "reject",
                "Environment variable overrides are forbidden for deletion commands",
            )
        if any(dangerous_env_key(key) for key in env):
            return Decision(
                "ask",
                "Environment changes command loading or interpretation; approval is required",
            )
        if self.dialect != "posix":
            reason = _legacy_approval_reason(command, self.trusted)
            return (
                Decision("ask", reason)
                if reason
                else Decision("allow", stdin_is_code=False)
            )
        tree = syntax or parse_script(command)
        keys = set(env)
        for item in tree.commands():
            keys.update(item.assignments)
            parts = [w.literal or w.raw for w in item.argv]
            if parts and parts[0] in {"export", "set", "unset"}:
                keys.update(
                    p.split("=", 1)[0] for p in parts[1:] if not p.startswith("-")
                )
            elif parts and parts[0] == "env":
                for index, part in enumerate(parts[1:], 1):
                    if re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", part):
                        keys.add(part.split("=", 1)[0])
                    elif part.startswith("--unset="):
                        keys.add(part.partition("=")[2])
                    elif part in {"-u", "--unset"} and index + 1 < len(parts):
                        keys.add(parts[index + 1])
        if self.allowed_env_keys is not None and not keys.issubset(
            self.allowed_env_keys
        ):
            return Decision(
                "reject", "Environment keys are outside the configured allowed_env_keys"
            )
        if may_delete(command) and (
            keys or session_state is not None and session_state.env
        ):
            return Decision(
                "reject",
                "Environment variable overrides are forbidden for deletion commands",
            )
        if any(
            dangerous_env_key(key)
            for key in keys | set(session_state.env if session_state else {})
        ):
            return Decision(
                "ask",
                "Environment changes command loading or interpretation; approval is required",
            )
        if tree.reasons():
            return Decision("ask", tree.reasons()[0] + "; approval is required")
        effects: set[Effect] = set()
        rejections: list[Decision] = []
        input_code = False
        cwd = self.cwd

        def writes(path: str) -> bool:
            candidate = Path(path)
            if (
                str(candidate).startswith("/workspace/")
                or str(candidate) == "/workspace"
            ):
                candidate = self.root / candidate.relative_to("/workspace")
            return (cwd / candidate).resolve().is_relative_to(self.root)

        def child_effects(nested: str | list[str]) -> set[Effect]:
            nonlocal input_code
            policy = ShellCommandPolicy(
                level=self.level,
                trusted_commands=self.trusted,
                blocked_commands=self.blocked,
                root=self.root,
                dialect=self.dialect,
                allowed_env_keys=self.allowed_env_keys,
                cwd=cwd,
            )
            child = policy.evaluate(
                nested, session_state=session_state, depth=depth + 1
            )
            input_code |= child.stdin_is_code
            if child.kind == "reject":
                rejections.append(child)
            return set(child.effects) or (
                {Effect.UNKNOWN} if child.kind != "allow" else {Effect.READ}
            )

        def inspect(node: Syntax) -> None:
            nonlocal cwd, input_code
            original_cwd = cwd
            if "||" in node.operators and any(
                cmd.argv and cmd.argv[0].literal == "cd" for cmd in node.commands()
            ):
                effects.add(Effect.UNKNOWN)
            for operator, target in node.redirects:
                if operator == "<":
                    continue
                effects.add(
                    Effect.WORKSPACE_WRITE
                    if target.literal is not None
                    and not target.has_glob
                    and writes(target.literal)
                    else Effect.UNKNOWN
                )
            if node.argv:
                parts = [w.literal for w in node.argv]
                if parts[0] == "export" and all(
                    "=" in w.raw and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", w.raw)
                    for w in node.argv[1:]
                ):
                    effects.add(Effect.READ)
                elif (
                    parts[0] == "echo"
                    and isinstance(command, str)
                    and any(part is None for part in parts[1:])
                ):
                    effects.add(Effect.READ)
                elif any(p is None for p in parts) or any(
                    w.has_glob and not (parts[0] == "find" and w.literal == "{}")
                    for w in node.argv
                ):
                    effects.add(Effect.UNKNOWN)
                else:
                    argv = [p for p in parts if p is not None]
                    name = argv[0]
                    capability = (
                        STDIN_SPECS.get(name)
                        or SPECS.get(" ".join(argv[:2]))
                        or SPECS.get(name)
                    )
                    code = (
                        capability.stdin_is_code
                        if capability
                        else name not in {"find", "command"}
                    )
                    input_code |= code
                    if node.stdin and code:
                        effects.add(Effect.UNKNOWN)
                    if name in DELETE_COMMANDS:
                        effects.add(Effect.DELETE)
                    elif name in SYSTEM_COMMANDS:
                        effects.add(Effect.SYSTEM)
                    elif not self._base_executable(
                        name, session_state, shell=isinstance(command, str), cwd=cwd
                    ):
                        effects.add(Effect.UNKNOWN)
                    else:
                        key = (
                            " ".join(argv[:2]) if " ".join(argv[:2]) in SPECS else name
                        )
                        declaration = SPECS.get(key)
                        args = argv[2:] if " " in key else argv[1:]
                        if name in {"head", "tail"}:
                            args = [
                                piece
                                for arg in args
                                for piece in (
                                    ["-n", arg[1:]]
                                    if re.fullmatch(r"-\d+", arg)
                                    else [arg]
                                )
                            ]
                        positions = (
                            arguments(declaration, args) if declaration else None
                        )
                        if declaration is not None and positions is not None:
                            effect = declaration.effect
                            targets: list[str] = []
                            for position in declaration.write_positions:
                                if position == -2:
                                    targets.extend(positions)
                                elif -len(positions) <= position < len(positions):
                                    targets.append(positions[position])
                            if (
                                name in {"cp", "mv"}
                                and positions
                                and len(positions) > 1
                            ):
                                destination = cwd / positions[-1]
                                if destination.is_dir():
                                    targets.extend(
                                        str(destination / Path(source).name)
                                        for source in positions[:-1]
                                    )
                            if targets:
                                effect = (
                                    Effect.WORKSPACE_WRITE
                                    if all(writes(p) for p in targets)
                                    else Effect.UNKNOWN
                                )
                            effects.add(effect)
                            if name == "cd":
                                if len(positions) == 1 and writes(positions[0]):
                                    cwd = (cwd / positions[0]).resolve()
                                else:
                                    effects.add(Effect.UNKNOWN)
                        elif (
                            len(argv) == 2
                            and argv[1] in {"--version", "-V"}
                            and name in STDIN_CODE
                        ):
                            effects.add(Effect.READ)
                        elif (
                            name == "uv"
                            and argv[1:2] == ["run"]
                            and self._nested(argv) is not None
                        ):
                            effects.add(Effect.PROJECT_CODE)
                            effects.update(child_effects(self._nested(argv) or []))
                        elif name in {"python", "python3"} and argv[1:3] == [
                            "-m",
                            "pytest",
                        ]:
                            effects.update(child_effects(["pytest", *argv[3:]]))
                        elif (
                            name == "env"
                            and self._nested(argv)
                            and all(
                                "=" in arg and not arg.startswith("-")
                                for arg in argv[
                                    1 : len(argv) - len(self._nested(argv) or [])
                                ]
                            )
                        ):
                            effects.update(child_effects(self._nested(argv) or []))
                        elif name == "sh" and len(argv) == 3 and argv[1] == "-c":
                            effects.update(child_effects(argv[2]))
                        elif name == "find":
                            effects.update(self._find_effect(argv, child_effects))
                            if node.stdin and input_code:
                                effects.add(Effect.UNKNOWN)
                        elif (
                            name == "command"
                            and len(argv) == 3
                            and argv[1] in {"-v", "-V"}
                        ):
                            effects.add(Effect.READ)
                        elif (
                            self._wildcard(argv)
                            and name
                            not in DELETE_COMMANDS
                            | (STDIN_CODE - {"uv"})
                            | {"sudo", "git", "npm", "pnpm"}
                            and not (name == "uv" and "publish" in argv)
                        ):
                            effects.add(Effect.READ)
                        else:
                            effects.add(Effect.UNKNOWN)
                            nested = self._nested(argv)
                            if nested is not None:
                                effects.update(child_effects(nested))
                    if "/" in name and (nested := self._nested(argv)) is not None:
                        effects.update(child_effects(nested))
            for child in node.children:
                inspect(child)
            if node.kind in {"subshell", "pipeline"}:
                cwd = original_cwd

        inspect(tree)
        for body in tree.shell_bodies():
            effects.update(child_effects(body))
        if rejections:
            return rejections[0]
        allowed = {Effect.READ}
        if self.level in {"workspace_write", "trusted_dev"}:
            allowed.add(Effect.WORKSPACE_WRITE)
        if self.level == "trusted_dev":
            allowed.update({Effect.NETWORK, Effect.PROJECT_CODE})
        denied = effects - allowed
        if denied:
            return Decision(
                "ask",
                "Shell effects require approval: " + ", ".join(sorted(denied)),
                input_code,
                frozenset(effects),
            )
        return Decision("allow", stdin_is_code=input_code, effects=frozenset(effects))

    def _find_effect(
        self, argv: list[str], child_effects: Callable[[list[str]], set[Effect]]
    ) -> set[Effect]:
        effects = {Effect.READ}
        index = 1
        while index < len(argv):
            arg = argv[index]
            if arg in {
                "-name",
                "-iname",
                "-path",
                "-ipath",
                "-type",
                "-maxdepth",
                "-mindepth",
            }:
                index += 2
                if index > len(argv):
                    return {Effect.UNKNOWN}
            elif arg in {
                "-print",
                "-print0",
                "-empty",
                "-readable",
                "-writable",
                "-executable",
                "-o",
                "-a",
                "!",
                "(",
                ")",
            }:
                index += 1
            elif arg in {"-exec", "-execdir"}:
                start = index + 1
                index = start
                while index < len(argv) and argv[index] not in {";", "+"}:
                    index += 1
                if index == start or index == len(argv):
                    return {Effect.UNKNOWN}
                child = [
                    "./discovered-file" if part == "{}" else part
                    for part in argv[start:index]
                ]
                effects.update(child_effects(child))
                index += 1
            elif arg.startswith("-"):
                return {Effect.UNKNOWN}
            else:
                index += 1
        return effects

    def _wildcard(self, argv: list[str]) -> bool:
        return any(
            rule.endswith(" *")
            and argv[: len(prefix := shlex.split(rule[:-2]))] == prefix
            for rule in self.trusted
        )

    def _base_executable(
        self, name: str, state: ShellSessionState | None, *, shell: bool, cwd: Path
    ) -> bool:
        if "/" in name or "\\" in name:
            return False
        if shell and name in {
            "cd",
            "echo",
            "printf",
            "pwd",
            "true",
            "false",
            "command",
        }:
            return True
        for directory in [cwd, *cwd.parents]:
            if not directory.is_relative_to(self.root):
                break
            candidate = directory / ".venv" / "bin" / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return False
        base = os.environ.get("PATH", os.defpath)
        resolved = shutil.which(name, path=base)
        if (
            resolved is None
            or not Path(resolved).is_absolute()
            or Path(resolved).is_relative_to(self.root)
            or Path(resolved).resolve().is_relative_to(self.root)
        ):
            return False
        if state and "PATH" in state.env:
            for entry in state.env["PATH"].split(":"):
                mapped = (
                    self.root / entry.removeprefix("/workspace/")
                    if entry.startswith("/workspace/")
                    else Path(entry)
                )
                if (
                    entry not in (state.base_path or base.split(":"))
                    and (mapped / name).is_file()
                ):
                    return False
        return True
