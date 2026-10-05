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


def executable_name(value: str) -> str:
    return PureWindowsPath(value).name.lower().removesuffix(".exe")


def shell_commands(script: str) -> list[list[str]]:
    script = re.sub(r"\\\r?\n", "", script).replace("\n", " ; ")
    lexer = shlex.shlex(script, posix=True, punctuation_chars=";|&<>()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    commands: list[list[str]] = []
    current: list[str] = []
    for token in lexer:
        if token and all(char in ";|&<>()" for char in token):
            if current:
                commands.append(current)
                current = []
        else:
            current.append(token)
    if current:
        commands.append(current)
    return commands


def unwrap_command(command: list[str]) -> list[str]:
    while command and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", command[0]):
        command = command[1:]
    while command and executable_name(command[0]) in WRAPPERS:
        command = command[1:]
        while command and (command[0].startswith("-") or "=" in command[0]):
            command = command[1:]
    return command


def inspected_commands(command: list[str] | str) -> list[list[str]]:
    commands = shell_commands(command) if isinstance(command, str) else [command]
    result: list[list[str]] = []
    for parts in commands:
        if parts:
            result.append(parts)
        parts = unwrap_command(parts)
        if not parts:
            continue
        if parts not in result:
            result.append(parts)
        if executable_name(parts[0]) in SHELL_COMMANDS:
            for index, part in enumerate(parts[1:], start=1):
                if part.lower() in {"-c", "-lc", "-command", "/c", "--command"}:
                    if index + 1 < len(parts):
                        result.extend(inspected_commands(parts[index + 1]))
                    break
    return result


def literal_command_reason(
    command: list[str] | str, *, dialect: ShellDialect | None = None, depth: int = 0
) -> str | None:
    dialect = dialect or ("cmd" if os.name == "nt" else "posix")
    if depth > 16:
        return "Nested shell commands exceed the inspection limit"
    if isinstance(command, str):
        reason = literal_script_reason(command, dialect)
        if reason is not None:
            return reason
    try:
        commands = inspected_commands(command)
    except (ValueError, RecursionError):
        return "Shell syntax could not be inspected"
    for parts in commands:
        name = executable_name(parts[0])
        if name in WRAPPERS and any(
            re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", part) for part in parts[1:]
        ):
            return "Environment variable assignments and overrides are forbidden"
        if name in {"find", "xargs"} and (
            "-delete" in parts
            or any(executable_name(part) in DELETE_COMMANDS for part in parts[1:])
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


def approval_reason(command: list[str] | str, trusted_commands: set[str]) -> str | None:
    if isinstance(command, str):
        if re.search(r"(?<!&)&(?!&)", command):
            return "Background commands require approval"
        if any(char in command for char in "<>\n"):
            return "Shell redirection or multiline scripts require approval"
        try:
            commands = shell_commands(command)
        except ValueError:
            return "Shell syntax could not be inspected; approval is required"
    else:
        commands = [command]
    for parts in commands:
        if not parts:
            continue
        name = executable_name(parts[0])
        if name in DELETE_COMMANDS:
            return "Deleting files requires approval"
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


def _exact_rule(rule: str, command: list[str]) -> bool:
    try:
        return shlex.split(rule) == command
    except ValueError:
        return False
