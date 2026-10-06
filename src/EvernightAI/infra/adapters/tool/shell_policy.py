import re
import shlex
import os
from pathlib import PureWindowsPath

from EvernightAI.infra.adapters.tool.shell_literals import (
    ShellDialect,
    literal_script_reason,
)


READ_COMMANDS = {
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
    commands = (
        shell_commands(command, ignore_redirections=ignore_redirections)
        if isinstance(command, str)
        else [command]
    )
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


def literal_command_reason(
    command: list[str] | str, *, dialect: ShellDialect | None = None, depth: int = 0
) -> str | None:
    dialect = dialect or ("cmd" if os.name == "nt" else "posix")
    if depth > 16:
        return "Nested shell commands exceed the inspection limit"
    deleting = contains_deletion(command)
    if isinstance(command, str):
        reason = literal_script_reason(command, dialect, strict_paths=deleting)
        if reason is not None:
            return reason
    try:
        commands = inspected_commands(command, ignore_redirections=True)
    except (ValueError, RecursionError):
        return "Shell syntax could not be inspected"
    for parts in commands:
        name = executable_name(parts[0])
        if (
            isinstance(command, str)
            and (
                "$" in parts[0]
                or dialect == "cmd"
                and re.search(r"%[^%]+%|![^!]+!", parts[0])
            )
            and not re.match(r"^(?:\$(?:env:)?)?[A-Za-z_][A-Za-z_0-9]*=", parts[0])
        ):
            return (
                "Command names must be literal so deletion operations can be inspected"
            )
        if (
            deleting
            and name in WRAPPERS
            and any(re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", part) for part in parts[1:])
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
        if deleting and (
            name in {"env", "export", "set", "setenv", "unset"}
            or re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", parts[0])
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
        if name not in SHELL_COMMANDS | WRAPPERS | {"uv", "find", "busybox"}:
            continue
        for index, part in enumerate(parts):
            shell = executable_name(part)
            if shell not in SHELL_COMMANDS:
                continue
            for flag_index in range(index + 1, len(parts) - 1):
                if parts[flag_index].lower() in {
                    "-c",
                    "-lc",
                    "-command",
                    "/c",
                    "--command",
                }:
                    nested_dialect: ShellDialect = (
                        "cmd"
                        if shell == "cmd"
                        else "powershell"
                        if shell in {"powershell", "pwsh"}
                        else "posix"
                    )
                    reason = literal_command_reason(
                        parts[flag_index + 1], dialect=nested_dialect, depth=depth + 1
                    )
                    if reason is not None:
                        return reason
                    break
    return None


def approval_reason(
    command: list[str] | str, trusted_commands: set[str], *, relaxed: bool = False
) -> str | None:
    if isinstance(command, str):
        try:
            if any(
                token == "&" and is_operator
                for token, is_operator in _shell_tokens(command)
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
                in {"-delete", "-fprint", "-fprint0", "-fprintf", "-fls", "-ok", "-okdir"}
                for part in parts[1:]
            ):
                return "Writing or interactive find actions require approval"
            nested_commands = _find_execution_commands(parts)
            if nested_commands is None:
                return "find execution actions could not be inspected; approval is required"
            for nested in nested_commands:
                reason = approval_reason(nested, trusted_commands, relaxed=relaxed)
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
        return not nested or approval_reason(nested, set(), relaxed=True) is None
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
            return bool(nested) and approval_reason(nested, set(), relaxed=True) is None
    if name in SHELL_COMMANDS:
        return (
            len(args) >= 2
            and args[0].lower() in {"-c", "-lc", "-command", "/c", "--command"}
            and approval_reason(args[1], set(), relaxed=True) is None
        )
    return False


def _exact_rule(rule: str, command: list[str]) -> bool:
    try:
        return shlex.split(rule) == command
    except ValueError:
        return False
