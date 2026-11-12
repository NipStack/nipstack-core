"""Strict textual frontend with bounded, explicit block declarations."""

from dataclasses import dataclass, field
from typing import Literal
from unicodedata import category

from ._regex import Regex, escape_literal
from .model import (
    Capture,
    CompiledBlock,
    CompiledNativeTemplate,
    LinePattern,
    NativeError,
    NativeLimits,
    Transformation,
    Validator,
)

_VALIDATORS: dict[str, Validator] = {
    "IPV4": "IPV4",
    "IPV6": "IPV6",
    "PREFIXV4": "PREFIXV4",
    "PREFIXV6": "PREFIXV6",
    "INT": "INT",
}

_DEFAULT_LIMITS = NativeLimits()


def _compile_regex(expression: str, limits: NativeLimits) -> Regex:
    compiled = Regex.compile(expression, memory=limits.max_re2_memory)
    if compiled is None:
        raise NativeError("INVALID_REGEX")
    return compiled


def _literal(text: str) -> str:
    parts: list[str] = []
    position = 0
    while position < len(text):
        end = position + 1
        if text[position] in " \t":
            while end < len(text) and text[end] in " \t":
                end += 1
            parts.append("[ \t]+")
        else:
            while end < len(text) and text[end] not in " \t":
                end += 1
            parts.append(escape_literal(text[position:end]))
        position = end
    return "".join(parts)


def _split_modifiers(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    quoted = escaped = False
    for index, character in enumerate(text):
        if character == '"' and not escaped:
            quoted = not quoted
        if character == "|" and not quoted:
            parts.append(text[start:index].strip())
            start = index + 1
        escaped = character == "\\" and not escaped
    if quoted:
        raise NativeError("INVALID_TEMPLATE")
    parts.append(text[start:].strip())
    return parts


def _delimiter(text: str) -> str:
    if len(text) < 2 or not text.startswith('"') or not text.endswith('"'):
        raise NativeError("INVALID_TEMPLATE")
    characters: list[str] = []
    escaped = False
    for character in text[1:-1]:
        if escaped:
            if character not in '\\"':
                raise NativeError("INVALID_TEMPLATE")
            characters.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"' or category(character) == "Cc":
            raise NativeError("INVALID_TEMPLATE")
        else:
            characters.append(character)
    if escaped or not characters:
        raise NativeError("INVALID_TEMPLATE")
    return "".join(characters)


def _identifier(name: str) -> bool:
    return name.isascii() and name.isidentifier()


def _capture(text: str, limits: NativeLimits) -> Capture:
    name, *modifiers = _split_modifiers(text)
    if not _identifier(name) or len(set(modifiers)) != len(modifiers):
        raise NativeError("INVALID_TEMPLATE")
    mode: Literal["token", "phrase"] = "token"
    constraint = None
    validator: Validator | None = None
    transformations: list[Transformation] = []
    value_type: Literal["string", "integer", "strings", "integers"] = "string"
    for modifier in modifiers:
        if modifier in ("required", "optional"):
            continue
        if modifier == "phrase" and mode == "token" and not transformations and validator is None:
            mode = "phrase"
        elif modifier.startswith('regex="') and modifier.endswith('"'):
            if constraint is not None or validator is not None or transformations:
                raise NativeError("INVALID_TEMPLATE")
            mode = "phrase"
            expression = modifier[7:-1]
            escaped = False
            for character in expression:
                if character == '"' and not escaped:
                    raise NativeError("INVALID_TEMPLATE")
                escaped = character == "\\" and not escaped
            if len(expression.encode("utf-8")) > limits.max_regex_bytes:
                raise NativeError("RESOURCE_LIMIT")
            constraint = _compile_regex(expression, limits)
        elif modifier in _VALIDATORS:
            if validator is not None or constraint is not None or transformations:
                raise NativeError("INVALID_TEMPLATE")
            validator = _VALIDATORS[modifier]
        elif modifier == "to_int" and value_type == "string":
            if validator is not None and validator != "INT":
                raise NativeError("UNSUPPORTED_COMPOSITION")
            transformations.append(Transformation("to_int"))
            value_type = "integer"
        elif modifier.startswith("split(") and modifier.endswith(")") and value_type == "string":
            transformations.append(Transformation("split", _delimiter(modifier[6:-1])))
            value_type = "strings"
        elif (
            modifier.startswith("expand_ranges(")
            and modifier.endswith(")")
            and value_type == "strings"
        ):
            delimiter = _delimiter(modifier[14:-1])
            if any(character in "0123456789" for character in delimiter):
                raise NativeError("INVALID_TEMPLATE")
            transformations.append(Transformation("expand_ranges", delimiter))
        elif modifier == "map_int" and value_type == "strings":
            transformations.append(Transformation("map_int"))
            value_type = "integers"
        else:
            raise NativeError("INVALID_TEMPLATE")
    if "required" in modifiers and "optional" in modifiers:
        raise NativeError("INVALID_TEMPLATE")
    return Capture(
        name,
        mode,
        "optional" in modifiers,
        "required" in modifiers,
        constraint,
        validator,
        tuple(transformations),
    )


def _parts(text: str, limits: NativeLimits) -> tuple[list[str], list[Capture]]:
    literals: list[str] = []
    captures: list[Capture] = []
    position = 0
    while True:
        start = text.find("{{", position)
        if start < 0:
            literals.append(text[position:])
            break
        literals.append(text[position:start])
        end = start + 2
        quoted = escaped = False
        while end < len(text):
            character = text[end]
            if character == '"' and not escaped:
                quoted = not quoted
            if not quoted and text.startswith("}}", end):
                break
            escaped = character == "\\" and not escaped
            end += 1
        else:
            raise NativeError("INVALID_TEMPLATE")
        captures.append(_capture(text[start + 2 : end], limits))
        if len(captures) > limits.max_captures:
            raise NativeError("RESOURCE_LIMIT")
        position = end + 2
    if any("{{" in literal or "}}" in literal for literal in literals):
        raise NativeError("INVALID_TEMPLATE")
    names = [capture.name for capture in captures if capture.name != "ignore"]
    if len(set(names)) != len(names):
        raise NativeError("INVALID_TEMPLATE")
    return literals, captures


def _pattern(text: str, limits: NativeLimits, *, child_record_header: bool = False) -> LinePattern:
    literals, captures = _parts(text, limits)
    middle = [
        index
        for index, capture in enumerate(captures)
        if capture.mode == "phrase" and (index < len(captures) - 1 or literals[-1])
    ]
    boundary = None
    if middle:
        index = middle[0]
        if (
            len(middle) != 1
            or any(capture.optional for capture in captures)
            or sum(capture.mode == "phrase" for capture in captures) != 1
            or not literals[index + 1].strip(" \t")
        ):
            raise NativeError("UNSUPPORTED_COMPOSITION")
        after = literals[index + 1]
        marker = "[ \t]" + _literal(after.lstrip(" \t"))
        boundary = (index, _compile_regex(marker, limits))
    structural: list[str] = []
    diagnostic: list[str] = []
    for index, capture in enumerate(captures):
        before, after = literals[index], literals[index + 1]
        final = index == len(captures) - 1 and not after
        if (
            capture.optional
            and not final
            or (before and before[-1] not in " \t")
            or (after and after[0] not in " \t")
            or (index > 0 and not before)
            or (capture.optional and not before)
        ):
            raise NativeError("UNSUPPORTED_COMPOSITION")
        if before.endswith((" ", "\t")):
            literal = _literal(before.rstrip(" \t"))
            separator = "[ \t]" if capture.mode != "token" else "[ \t]+"
            structural.append(literal)
            segment = separator
            # Missing captures may omit their separator, never extend a literal word.
            diagnostic.append(literal)
            invalid_segment = (
                r"[ \t]+[^\r\n]*" if final or capture.mode == "phrase" else r"[ \t]+[^ \t\r\n]+"
            )
            diagnostic.append("(?:" + invalid_segment + ")?")
        else:
            segment = ""
            diagnostic.append(r"[^\r\n]*" if final else r"[^ \t\r\n]*")
        segment += r"([^ \t\r\n]+)" if capture.mode == "token" else r"([^\r\n]*)"
        structural.append("(?:" + segment + ")?" if capture.optional else segment)
    structural.append(_literal(literals[-1]))
    diagnostic.append(_literal(literals[-1]))
    if literals[-1] and (captures or child_record_header):
        diagnostic.append(r"(?:[ \t]+[^\r\n]*)?")
    return LinePattern(
        tuple(captures),
        _compile_regex("".join(structural), limits),
        _compile_regex("".join(diagnostic), limits),
        any(capture.required for capture in captures),
        "".join(structural),
        boundary,
    )


@dataclass(slots=True)
class _BlockBuilder:
    kind: Literal["section", "record"]
    name: str | None
    header_indentation: str | None = None
    indentation: str = ""
    headers: list[LinePattern] = field(default_factory=list)
    body: list[LinePattern] = field(default_factory=list)
    children: list[CompiledBlock] = field(default_factory=list)

    def member_indentation(self, prefix: str) -> None:
        assert self.header_indentation is not None
        if (
            prefix == self.header_indentation
            or not prefix.startswith(self.header_indentation)
            or (self.indentation and prefix != self.indentation)
        ):
            raise NativeError("INVALID_TEMPLATE")
        self.indentation = prefix

    def finish(self) -> CompiledBlock:
        if not self.headers:
            raise NativeError("INVALID_TEMPLATE")
        names = [child.name for child in self.children]
        fields = {
            capture.name
            for pattern in (*self.headers, *self.body)
            for capture in pattern.captures
            if capture.name != "ignore"
        }
        if len(set(names)) != len(names) or any(name in fields for name in names):
            raise NativeError("INVALID_TEMPLATE")
        assert self.header_indentation is not None
        return CompiledBlock(
            self.kind,
            self.name,
            tuple(self.headers),
            tuple(self.body),
            self.header_indentation,
            self.indentation,
            tuple(self.children),
        )


def compile_native(
    body: bytes, *, limits: NativeLimits = _DEFAULT_LIMITS
) -> CompiledNativeTemplate:
    """Compile body bytes only, without resolving resources or performing I/O."""
    if not isinstance(body, bytes) or not isinstance(limits, NativeLimits):
        raise NativeError("INVALID_ARGUMENT")
    if len(body) > limits.max_template_bytes:
        raise NativeError("RESOURCE_LIMIT")
    text = None
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if text is None or text.startswith("\ufeff") or "\r" in text.replace("\r\n", ""):
        raise NativeError("INVALID_ENCODING")
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    if len(lines) > limits.max_lines:
        raise NativeError("RESOURCE_LIMIT")
    stack: list[_BlockBuilder] = []
    root: CompiledBlock | None = None
    pattern_count = capture_count = 0
    for line in lines:
        line = line.removesuffix("\r")
        if len(line) > limits.max_line_characters:
            raise NativeError("RESOURCE_LIMIT")
        if not line.strip() or line.lstrip(" \t").startswith("#"):
            continue
        directive = line.lstrip(" \t")
        if directive.startswith("@"):
            words = directive.split(" ")
            if words[0] in ("@section", "@record"):
                kind: Literal["section", "record"] = (
                    "section" if words[0] == "@section" else "record"
                )
                if not stack:
                    if root is not None or len(words) != 1:
                        raise NativeError("INVALID_TEMPLATE")
                    stack.append(_BlockBuilder(kind, None))
                else:
                    if (
                        len(stack) != 1
                        or not stack[0].headers
                        or len(words) != 2
                        or not _identifier(words[1])
                    ):
                        raise NativeError("INVALID_TEMPLATE")
                    stack.append(_BlockBuilder(kind, words[1]))
            elif words == ["@end"] and stack:
                finished = stack.pop().finish()
                if stack:
                    stack[-1].children.append(finished)
                else:
                    root = finished
            else:
                raise NativeError("INVALID_TEMPLATE")
            continue
        if not stack or line.endswith((" ", "\t")):
            raise NativeError("INVALID_TEMPLATE")
        current = stack[-1]
        prefix = line[: len(line) - len(line.lstrip(" \t"))]
        header = not current.headers
        if header:
            if len(stack) == 1 and prefix:
                raise NativeError("INVALID_TEMPLATE")
            if len(stack) > 1:
                stack[-2].member_indentation(prefix)
            current.header_indentation = prefix
        elif prefix == current.header_indentation:
            if current.kind != "record" or current.name is None or current.body:
                raise NativeError("INVALID_TEMPLATE")
            header = True
        else:
            current.member_indentation(prefix)
        if (
            header
            and current.name is not None
            and current.kind == "record"
            and line[len(prefix) :].startswith("|")
        ):
            raise NativeError("INVALID_TEMPLATE")
        if pattern_count >= limits.max_patterns:
            raise NativeError("RESOURCE_LIMIT")
        pattern = _pattern(
            line[len(prefix) :],
            limits,
            child_record_header=header and current.kind == "record" and current.name is not None,
        )
        if header and any(capture.optional or capture.required for capture in pattern.captures):
            raise NativeError("INVALID_TEMPLATE")
        if not header and not pattern.captures:
            raise NativeError("INVALID_TEMPLATE")
        if header and any(
            previous.structural_key == pattern.structural_key for previous in current.headers
        ):
            raise NativeError("INVALID_TEMPLATE")
        (current.headers if header else current.body).append(pattern)
        pattern_count += 1
        capture_count += len(pattern.captures)
        if capture_count > limits.max_captures:
            raise NativeError("RESOURCE_LIMIT")
    if root is None or stack:
        raise NativeError("INVALID_TEMPLATE")
    return CompiledNativeTemplate(root, limits)
