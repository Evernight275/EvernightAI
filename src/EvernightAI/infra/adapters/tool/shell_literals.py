import re
from typing import Literal

from EvernightAI.infra.adapters.tool.shell_heredocs import parse_quoted_heredocs


ShellDialect = Literal["posix", "cmd", "powershell"]


def literal_script_reason(
    script: str, dialect: ShellDialect = "posix", *, strict_paths: bool = True
) -> str | None:
    if dialect == "posix":
        try:
            parsed = parse_quoted_heredocs(script)
        except ValueError as exc:
            return str(exc)
        if strict_paths and parsed.here_documents:
            return "Here-documents are forbidden for deletion commands; use literal paths"
        script = parsed.text
    if (
        strict_paths
        and dialect == "cmd"
        and re.search(r"%[^%\s]+%|![^!\s]+!|%[0-9*]", script)
    ):
        return "Environment variable expansion is forbidden"
    quote: str | None = None
    word_start = True
    index = 0
    while index < len(script):
        char = script[index]
        following = script[index + 1 : index + 2]
        if quote == "'":
            if char == "'":
                if dialect == "powershell" and following == "'":
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        escape = "^" if dialect == "cmd" else "`" if dialect == "powershell" else "\\"
        if char == escape and (quote is None or dialect != "cmd"):
            if not following:
                return "Incomplete shell escaping is forbidden"
            if dialect == "posix" and quote == '"' and following not in '$`"\\\n':
                index += 1
                continue
            index += 2
            word_start = False
            continue
        if char == '"' or (char == "'" and dialect != "cmd"):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            word_start = False
            index += 1
            continue
        if dialect != "cmd" and char == "$":
            if following == "(":
                return "Command substitution is forbidden"
            if strict_paths:
                return "Environment and shell variable expansion is forbidden; quote or escape literal $"
        if dialect == "posix" and char == "`":
            return "Command substitution is forbidden"
        if quote is None:
            if char in "()":
                return "Shell grouping and computed arguments are forbidden"
            if char == "<" and following == "<":
                return (
                    "Here-documents and here-strings are forbidden; use literal paths"
                )
            if char in "<>" and following == "(":
                return "Process substitution is forbidden; use literal paths"
            if strict_paths and char in "*?[":
                return "Wildcard expansion is forbidden; quote or escape literal filename characters"
            if strict_paths and dialect != "cmd" and char == "~" and word_start:
                return "Home-directory expansion is forbidden; use a literal relative or absolute path"
            if (
                strict_paths
                and char == "{"
                and re.match(r"\{[^{}\s]*(?:,|\.\.)[^{}\s]*\}", script[index:])
            ):
                return "Brace expansion is forbidden; use literal paths"
            if char == "#" and word_start and dialect != "cmd":
                newline = script.find("\n", index)
                index = len(script) if newline < 0 else newline
                continue
            word_start = char.isspace() or char in ";|&()<>=:"
        index += 1
    if quote is not None:
        return "Unterminated shell quoting is forbidden"
    return None
