"""POSIX syntax inspection. Unknown syntax always remains visible as opaque."""

import shlex
from dataclasses import dataclass, field

import tree_sitter_bash
from tree_sitter import Language, Node, Parser


@dataclass(frozen=True)
class Word:
    literal: str | None
    raw: str
    has_glob: bool = False


@dataclass
class Syntax:
    kind: str
    operators: list[str] = field(default_factory=list)
    stdin_sources: list[str] = field(default_factory=list)
    body: str | None = None
    children: list["Syntax"] = field(default_factory=list)
    argv: list[Word] = field(default_factory=list)
    assignments: list[str] = field(default_factory=list)
    redirects: list[tuple[str, Word]] = field(default_factory=list)
    stdin: bool = False
    opaque: list[str] = field(default_factory=list)

    def commands(self) -> list["Syntax"]:
        return ([self] if self.argv or self.assignments else []) + [
            command for child in self.children for command in child.commands()
        ]

    def shell_bodies(self) -> list[str]:
        def bodies(node: "Syntax") -> list[str]:
            return ([node.body] if node.body is not None else []) + [
                body for child in node.children for body in bodies(child)
            ]

        if any(
            command.stdin
            and command.argv
            and command.argv[0].literal
            in {"sh", "bash", "dash", "zsh", "/bin/sh", "/bin/bash"}
            for command in self.commands()
        ):
            return bodies(self)
        return []

    def reasons(self) -> list[str]:
        return self.opaque + [
            reason for child in self.children for reason in child.reasons()
        ]


def parse_script(command: str | list[str]) -> Syntax:
    if isinstance(command, list):
        return Syntax("command", argv=[Word(part, part) for part in command])
    source = command.encode()
    parser = Parser(Language(tree_sitter_bash.language()))
    root = parser.parse(source).root_node

    def raw(node: Node) -> str:
        return source[node.start_byte : node.end_byte].decode()

    def word(node: Node) -> Word:
        text = raw(node)
        known = {
            "word",
            "string",
            "raw_string",
            "concatenation",
            "number",
            "simple_expansion",
            "expansion",
            "variable_name",
            "special_variable_name",
            "string_content",
            "variable_assignment",
        }
        dynamic = any(n.type not in known for n in descendants(node)) or any(
            n.type
            in {
                "expansion",
                "simple_expansion",
                "command_substitution",
                "process_substitution",
                "arithmetic_expansion",
                "brace_expression",
            }
            for n in descendants(node)
        )
        try:
            values = shlex.split(text)
            literal = values[0] if len(values) == 1 and not dynamic else None
        except ValueError:
            literal = None
        # Unquoted glob/tilde/brace syntax may change argument cardinality.
        glob = _has_pattern(text)
        return Word(literal, text, glob)

    def visit(node: Node, stdin: bool = False) -> Syntax:
        result = Syntax(node.type, stdin=stdin)
        result.operators = [
            child.type
            for child in node.children
            if child.type in {"&&", "||", "|", "|&", ";", "&"}
        ]
        if stdin:
            result.stdin_sources.append("pipe")
        if node.type in {
            "program",
            "list",
            "subshell",
            "pipeline",
            "redirected_statement",
        }:
            for index, child in enumerate(node.named_children):
                if child.type in {
                    "file_redirect",
                    "heredoc_redirect",
                    "herestring_redirect",
                }:
                    if child.type == "file_redirect":
                        target = child.child_by_field_name("destination")
                        operator = (
                            raw(child).split(raw(target), 1)[0].strip()
                            if target
                            else "?"
                        )
                        if target is None or operator not in {
                            "<",
                            ">",
                            ">>",
                            "1>",
                            "1>>",
                            "2>",
                            "2>>",
                        }:
                            result.opaque.append("Unsupported redirection")
                        elif operator == "<":
                            result.stdin = True
                            result.stdin_sources.append("redirect")
                            result.redirects.append((operator, word(target)))
                        else:
                            result.redirects.append((operator, word(target)))
                    elif child.type == "heredoc_redirect":
                        start = next(
                            (
                                n
                                for n in child.named_children
                                if n.type == "heredoc_start"
                            ),
                            None,
                        )
                        result.stdin = True
                        result.stdin_sources.append("heredoc")
                        if start is None or not raw(start).startswith(("'", '"')):
                            result.opaque.append("Unquoted heredoc")
                        # Keep body for nested shell inspection and hard deletion checks.
                        body = next(
                            (
                                n
                                for n in child.named_children
                                if n.type == "heredoc_body"
                            ),
                            None,
                        )
                        if body is not None:
                            result.children.append(Syntax("heredoc", body=raw(body)))
                    else:
                        result.opaque.append("Here-string")
                        result.stdin = True
                else:
                    result.children.append(
                        visit(child, stdin or node.type == "pipeline" and index > 0)
                    )
            if result.stdin:
                for child in result.children:
                    for cmd in child.commands():
                        cmd.stdin = True
                        cmd.stdin_sources.extend(result.stdin_sources)
            if any(c.type == "&" for c in node.children):
                result.opaque.append("Background shell syntax")
        elif node.type == "command":
            for child in node.named_children:
                if child.type == "variable_assignment":
                    key = child.child_by_field_name("name")
                    if key is not None:
                        result.assignments.append(raw(key))
                elif child.type == "command_name":
                    result.argv.append(
                        word(child.named_children[0])
                        if child.named_children
                        else word(child)
                    )
                elif child.type in {
                    "word",
                    "string",
                    "raw_string",
                    "concatenation",
                    "number",
                    "simple_expansion",
                    "expansion",
                }:
                    result.argv.append(word(child))
                else:
                    result.opaque.append(f"Unsupported command node: {child.type}")
        elif node.type == "variable_assignment":
            if any(
                child.type in {"array", "subscript", "arithmetic_expansion"}
                for child in descendants(node)
            ):
                result.opaque.append("Unsupported assignment syntax")
            key = node.child_by_field_name("name")
            if key is not None:
                result.assignments.append(raw(key))
        elif node.type in {"declaration_command", "unset_command"}:
            name = raw(node).split()[0]
            result.argv = [Word(name, name)]
            for child in node.named_children:
                result.argv.append(word(child))
                if child.type == "variable_assignment":
                    key = child.child_by_field_name("name")
                    if key is not None:
                        result.assignments.append(raw(key))
        elif node.type != "comment":
            result.opaque.append(f"Unsupported syntax: {node.type}")
            result.children = [visit(child, stdin) for child in node.named_children]
        if any(
            n.type
            in {"command_substitution", "process_substitution", "arithmetic_expansion"}
            for n in descendants(node)
        ):
            result.opaque.append("Substitution or arithmetic requires approval")
        return result

    try:
        result = visit(root)
    except RecursionError:
        return Syntax("program", opaque=["Shell syntax exceeds the inspection limit"])
    if root.has_error:
        result.opaque.append("Shell parse error")
    return result


def descendants(node: Node) -> list[Node]:
    return [node] + [
        nested
        for child in node.named_children
        if child.type != "heredoc_body"
        for nested in descendants(child)
    ]


def _has_pattern(text: str) -> bool:
    quote: str | None = None
    escaped = False
    for char in text:
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        elif quote is None and char in "*?[]{}~":
            return True
    return False
