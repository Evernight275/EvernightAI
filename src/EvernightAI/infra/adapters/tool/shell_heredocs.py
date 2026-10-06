from dataclasses import dataclass


@dataclass(frozen=True)
class HereDocument:
    header: str
    body: str


@dataclass(frozen=True)
class ShellScript:
    text: str
    here_documents: tuple[HereDocument, ...] = ()


def parse_quoted_heredocs(script: str) -> ShellScript:
    lines = script.split("\n")
    output: list[str] = []
    documents: list[HereDocument] = []
    quote: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        spans, quote, continued, compound = _headers(line, quote)
        if spans and (quote is not None or continued or compound):
            raise ValueError(
                "Here-document headers must contain one complete foreground command"
            )
        header = line
        for start, end, _, _ in reversed(spans):
            header = header[:start] + " " + header[end:]
        output.append(header)
        index += 1
        for _, _, delimiter, strip_tabs in spans:
            body: list[str] = []
            while index < len(lines):
                content = lines[index].lstrip("\t") if strip_tabs else lines[index]
                index += 1
                output.append("")
                if content == delimiter:
                    break
                body.append(content)
            else:
                raise ValueError("Here-document closing delimiter is missing")
            documents.append(HereDocument(header, "\n".join(body)))
    return ShellScript("\n".join(output), tuple(documents))


def _headers(
    line: str, quote: str | None
) -> tuple[list[tuple[int, int, str, bool]], str | None, bool, bool]:
    spans: list[tuple[int, int, str, bool]] = []
    index = 0
    word_start = True
    continued = False
    compound = False
    while index < len(line):
        char = line[index]
        if quote == "'":
            if char == "'":
                quote = None
            index += 1
            continue
        if char == "\\":
            continued = index + 1 == len(line)
            index += 2
            word_start = False
            continue
        if quote == '"':
            if char == '"':
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            word_start = False
            continue
        if char == "#" and word_start:
            break
        if char in ";|()" or (
            char == "&" and (index == 0 or line[index - 1] not in "<>")
        ):
            compound = True
        if line.startswith("<<", index):
            if line.startswith("<<<", index):
                raise ValueError("Here-strings are forbidden; use a quoted here-document")
            start = index
            index += 2
            strip_tabs = line[index : index + 1] == "-"
            if strip_tabs:
                index += 1
            while index < len(line) and line[index] in " \t":
                index += 1
            delimiter, index = _delimiter(line, index)
            fd_start = start
            while fd_start > 0 and line[fd_start - 1] in "0123456789":
                fd_start -= 1
            if fd_start == 0 or line[fd_start - 1] in " \t":
                start = fd_start
            spans.append((start, index, delimiter, strip_tabs))
            word_start = False
            continue
        word_start = char in " \t;|&<>()"
        index += 1
    return spans, quote, continued, compound


def _delimiter(line: str, index: int) -> tuple[str, int]:
    if index >= len(line) or line[index] not in {"'", '"'}:
        raise ValueError(
            "Here-document delimiters must be quoted to disable shell expansion"
        )
    quote = line[index]
    index += 1
    value: list[str] = []
    while index < len(line):
        char = line[index]
        if char == quote:
            index += 1
            if index < len(line) and line[index] not in " \t;|&<>()":
                raise ValueError(
                    "Here-document delimiters must be one quoted literal word"
                )
            return "".join(value), index
        if (
            quote == '"'
            and char == "\\"
            and line[index + 1 : index + 2] in {'"', "\\", "$", "`"}
        ):
            index += 1
            char = line[index]
        value.append(char)
        index += 1
    raise ValueError("Here-document delimiter quoting is incomplete")
