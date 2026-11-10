"""Strict textual frontend; only deterministic 40B capture compositions compile."""

from typing import Literal

from ._regex import Regex, escape_literal
from .model import Capture, CompiledNativeTemplate, LinePattern, NativeError, NativeLimits

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


def _capture(text: str, limits: NativeLimits) -> Capture:
    name, *modifiers = _split_modifiers(text)
    if (
        not name
        or name[0] not in "_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        or any(
            c not in "_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for c in name
        )
        or len(set(modifiers)) != len(modifiers)
    ):
        raise NativeError("INVALID_TEMPLATE")
    mode: Literal["token", "rest", "regex"] = "token"
    constraint = None
    for modifier in modifiers:
        if modifier in ("required", "optional"):
            continue
        if modifier == "rest" and mode == "token":
            mode = "rest"
        elif modifier.startswith('regex="') and modifier.endswith('"') and mode == "token":
            mode = "regex"
            expression = modifier[7:-1]
            escaped = False
            for character in expression:
                if character == '"' and not escaped:
                    raise NativeError("INVALID_TEMPLATE")
                escaped = character == "\\" and not escaped
            if len(expression.encode("utf-8")) > limits.max_regex_bytes:
                raise NativeError("RESOURCE_LIMIT")
            constraint = _compile_regex(expression, limits)
        else:
            raise NativeError("INVALID_TEMPLATE")
    if "required" in modifiers and "optional" in modifiers:
        raise NativeError("INVALID_TEMPLATE")
    return Capture(name, mode, "optional" in modifiers, "required" in modifiers, constraint)


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


def _pattern(text: str, limits: NativeLimits) -> LinePattern:
    literals, captures = _parts(text, limits)
    structural: list[str] = []
    diagnostic: list[str] = []
    for index, capture in enumerate(captures):
        before, after = literals[index], literals[index + 1]
        final = index == len(captures) - 1 and not after
        if (
            (capture.mode != "token" or capture.optional)
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
            invalid_segment = r"[ \t]+[^\r\n]*" if final else r"[ \t]+[^ \t\r\n]+"
            diagnostic.append("(?:" + invalid_segment + ")?")
        else:
            segment = ""
            diagnostic.append(r"[^\r\n]*" if final else r"[^ \t\r\n]*")
        segment += r"([^ \t\r\n]+)" if capture.mode == "token" else r"([^\r\n]*)"
        structural.append("(?:" + segment + ")?" if capture.optional else segment)
    structural.append(_literal(literals[-1]))
    diagnostic.append(_literal(literals[-1]))
    if captures and literals[-1]:
        diagnostic.append(r"(?:[ \t]+[^\r\n]*)?")
    return LinePattern(
        tuple(captures),
        _compile_regex("".join(structural), limits),
        _compile_regex("".join(diagnostic), limits),
        any(capture.required for capture in captures),
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
    kind: Literal["section", "record"] | None = None
    patterns: list[LinePattern] = []
    indentation = ""
    closed = False
    for line in lines:
        line = line.removesuffix("\r")
        if len(line) > limits.max_line_characters:
            raise NativeError("RESOURCE_LIMIT")
        if not line.strip() or line.lstrip(" \t").startswith("#"):
            continue
        if line.startswith("@"):
            if line in ("@section", "@record") and kind is None and not closed:
                kind = "section" if line == "@section" else "record"
            elif line == "@end" and kind is not None and patterns and not closed:
                closed = True
            else:
                raise NativeError("INVALID_TEMPLATE")
            continue
        if kind is None or closed or line.endswith((" ", "\t")):
            raise NativeError("INVALID_TEMPLATE")
        prefix = line[: len(line) - len(line.lstrip(" \t"))]
        if not patterns:
            if prefix:
                raise NativeError("INVALID_TEMPLATE")
        elif not prefix or (indentation and prefix != indentation):
            raise NativeError("INVALID_TEMPLATE")
        else:
            indentation = prefix
        pattern = _pattern(line[len(prefix) :], limits)
        if not patterns and any(
            capture.optional or capture.required for capture in pattern.captures
        ):
            raise NativeError("INVALID_TEMPLATE")
        if patterns and not pattern.captures:
            raise NativeError("INVALID_TEMPLATE")
        patterns.append(pattern)
        if len(patterns) > limits.max_patterns:
            raise NativeError("RESOURCE_LIMIT")
        if sum(len(p.captures) for p in patterns) > limits.max_captures:
            raise NativeError("RESOURCE_LIMIT")
    if kind is None or not closed:
        raise NativeError("INVALID_TEMPLATE")
    return CompiledNativeTemplate(kind, patterns[0], tuple(patterns[1:]), indentation, limits)
