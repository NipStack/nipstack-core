"""Pure, bounded line matching and isolated root-block execution."""

import json

from nipstack_core.contracts.json_data import JSONDocument, JSONValue, _freeze_json_document

from .model import CompiledNativeTemplate, LinePattern, NativeError


def _values(pattern: LinePattern, text: str) -> tuple[str | None, ...] | None:
    values = pattern.structural.groups(text)
    if values is None:
        return None
    for capture, value in zip(pattern.captures, values, strict=True):
        if value is not None and capture.constraint is not None:
            if not capture.constraint.accepts(value):
                return None
    return values


def _store(
    target: dict[str, JSONValue], pattern: LinePattern, values: tuple[str | None, ...]
) -> int:
    size = 0
    for capture, value in zip(pattern.captures, values, strict=True):
        if capture.name == "ignore" or value is None:
            continue
        if capture.name in target:
            raise NativeError("DUPLICATE_CAPTURE")
        size += len(json.dumps(capture.name, ensure_ascii=False).encode("utf-8"))
        size += len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        size += 1 + bool(target)
        target[capture.name] = value
    return size


def parse_native(template: CompiledNativeTemplate, text: str) -> JSONDocument:
    """Parse explicit text, emitting frozen JSON only after all blocks validate.

    Top-level lines close the previous block before header selection. Runtime
    state belongs to this invocation; no resource resolution or I/O occurs here.
    """
    if not isinstance(template, CompiledNativeTemplate) or not isinstance(text, str):
        raise NativeError("INVALID_ARGUMENT")
    limits = template.limits
    if len(text) > limits.max_input_bytes:
        raise NativeError("RESOURCE_LIMIT")
    encoded = None
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        pass
    if encoded is None or "\r" in text.replace("\r\n", "") or text.startswith("\ufeff"):
        raise NativeError("INVALID_ENCODING")
    if len(encoded) > limits.max_input_bytes:
        raise NativeError("RESOURCE_LIMIT")
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    if len(lines) > limits.max_lines:
        raise NativeError("RESOURCE_LIMIT")
    records: list[JSONValue] = []
    active: dict[str, JSONValue] | None = None
    seen: set[int] = set()
    selected = 0
    output_bytes = 2
    if output_bytes > limits.max_output_bytes:
        raise NativeError("RESOURCE_LIMIT")

    def close() -> None:
        nonlocal active
        if active is not None:
            if any(
                pattern.required and index not in seen
                for index, pattern in enumerate(template.body)
            ):
                raise NativeError("MISSING_REQUIRED")
            records.append(active)
            active = None

    for number, line in enumerate(lines, 1):
        line = line.removesuffix("\r")
        if len(line) > limits.max_line_characters:
            raise NativeError("RESOURCE_LIMIT", line=number)
        if not line.strip(" \t"):
            continue
        if line[0] not in " \t":
            close()
            values = _values(template.header, line)
            if values is None:
                # Regex selection failure is not a malformed header.
                if template.header.structural.groups(line) is None:
                    if template.header.diagnostic.accepts(line):
                        raise NativeError("MALFORMED_LINE", line=number)
                continue
            selected += 1
            if template.kind == "section" and selected > 1:
                raise NativeError("DUPLICATE_SECTION", line=number)
            if selected > limits.max_records:
                raise NativeError("RESOURCE_LIMIT", line=number)
            active = {}
            seen = set()
            if template.kind == "record":
                output_bytes += 2 + bool(records)
            output_bytes += _store(active, template.header, values)
        elif active is not None:
            content = line.lstrip(" \t")
            prefix = line[: len(line) - len(content)]
            accepted = []
            recognized = 0
            for index, pattern in enumerate(template.body):
                values = _values(pattern, content)
                if values is not None:
                    accepted.append((index, pattern, values))
                elif pattern.diagnostic.accepts(content):
                    recognized += 1
            if accepted or recognized:
                if prefix != template.indentation:
                    raise NativeError("INVALID_INDENTATION", line=number)
                if len(accepted) > 1 or (not accepted and recognized > 1):
                    raise NativeError("AMBIGUOUS_MATCH", line=number)
                if not accepted:
                    raise NativeError("MALFORMED_LINE", line=number)
                index, pattern, values = accepted[0]
                if index in seen:
                    raise NativeError("DUPLICATE_CAPTURE", line=number)
                seen.add(index)
                output_bytes += _store(active, pattern, values)
        if output_bytes > limits.max_output_bytes:
            raise NativeError("RESOURCE_LIMIT", line=number)
    close()
    if template.kind == "section":
        if not records:
            raise NativeError("MISSING_SECTION")
        return _freeze_json_document(records[0])
    return _freeze_json_document(records)
