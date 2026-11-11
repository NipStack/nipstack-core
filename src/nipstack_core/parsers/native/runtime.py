"""Pure, bounded line matching and isolated root-block execution."""

from dataclasses import dataclass, field

from nipstack_core.contracts.json_data import JSONDocument, JSONValue, _freeze_json_document

from .capture_values import ValueBudget, json_bytes, transform_value, validates
from .model import CompiledBlock, CompiledNativeTemplate, LinePattern, NativeError


def _values(pattern: LinePattern, text: str) -> tuple[str | None, ...] | None:
    values = pattern.structural.groups(text)
    if values is None:
        return None
    if pattern.phrase_boundary is not None:
        index, boundary = pattern.phrase_boundary
        start = pattern.structural.capture_start(text, index + 1)
        if boundary.has_multiple_boundaries(text, start):
            raise NativeError("AMBIGUOUS_MATCH")
    for capture, value in zip(pattern.captures, values, strict=True):
        if value is not None and capture.constraint is not None:
            if not capture.constraint.accepts(value):
                return None
        if value is not None and capture.validator is not None:
            if not validates(capture.validator, value):
                return None
    return values


def _insert(target: dict[str, JSONValue], name: str, value: JSONValue) -> int:
    if name in target:
        raise NativeError("DUPLICATE_CAPTURE")
    size = json_bytes(name) + 1 + bool(target) + json_bytes(value)
    target[name] = value
    return size


def _store(
    target: dict[str, JSONValue],
    pattern: LinePattern,
    values: tuple[str | None, ...],
    budget: ValueBudget,
) -> int:
    size = 0
    for capture, value in zip(pattern.captures, values, strict=True):
        if value is None:
            continue
        transformed = transform_value(capture, value, budget)
        if capture.name == "ignore":
            continue
        size += _insert(target, capture.name, transformed)
    return size


@dataclass(slots=True)
class _Frame:
    block: CompiledBlock
    data: dict[str, JSONValue]
    seen: set[int] = field(default_factory=set)


def parse_native(template: CompiledNativeTemplate, text: str) -> JSONDocument:
    """Parse explicit text, emitting frozen JSON only after all blocks validate.

    Top-level lines close the previous block before header selection. Runtime
    state belongs to this invocation; no resource resolution or I/O occurs here.
    """
    if not isinstance(template, CompiledNativeTemplate) or not isinstance(text, str):
        raise NativeError("INVALID_ARGUMENT")
    limits = template.limits
    budget = ValueBudget(limits)
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
    frames: list[_Frame] = []
    skipped: str | None = None
    selected = 0
    root_occurrences = 0
    output_bytes = 2
    if output_bytes > limits.max_output_bytes:
        raise NativeError("RESOURCE_LIMIT")

    def close() -> None:
        frame = frames.pop()
        if any(
            pattern.required and index not in frame.seen
            for index, pattern in enumerate(frame.block.body)
        ):
            raise NativeError("MISSING_REQUIRED")

    def open_block(
        block: CompiledBlock, pattern: LinePattern, values: tuple[str | None, ...]
    ) -> None:
        nonlocal selected, output_bytes, root_occurrences
        selected += 1
        if selected > limits.max_records:
            raise NativeError("RESOURCE_LIMIT")
        data: dict[str, JSONValue] = {}
        if frames:
            parent = frames[-1].data
            assert block.name is not None
            if block.kind == "section":
                if block.name in parent:
                    raise NativeError("DUPLICATE_SECTION")
                output_bytes += _insert(parent, block.name, data)
            else:
                collection = parent[block.name]
                assert isinstance(collection, list)
                output_bytes += 2 + bool(collection)
                collection.append(data)
        else:
            root_occurrences += 1
            if block.kind == "section" and root_occurrences > 1:
                raise NativeError("DUPLICATE_SECTION")
            if block.kind == "record":
                output_bytes += 2 + bool(records)
            records.append(data)
        for child in block.children:
            if child.kind == "record":
                assert child.name is not None
                output_bytes += _insert(data, child.name, [])
        output_bytes += _store(data, pattern, values, budget)
        frames.append(_Frame(block, data))

    for number, line in enumerate(lines, 1):
        line = line.removesuffix("\r")
        if len(line) > limits.max_line_characters:
            raise NativeError("RESOURCE_LIMIT", line=number)
        if not line.strip(" \t"):
            continue
        if line[0] not in " \t":
            while frames:
                close()
            skipped = None
            header = template.root.headers[0]
            values = _values(header, line)
            if values is None:
                # Regex selection failure is not a malformed header.
                if header.structural.groups(line) is None:
                    if header.diagnostic.accepts(line):
                        raise NativeError("MALFORMED_LINE", line=number)
                continue
            open_block(template.root, header, values)
        elif frames:
            content = line.lstrip(" \t")
            prefix = line[: len(line) - len(content)]
            if skipped is not None:
                if prefix != skipped and prefix.startswith(skipped):
                    continue
                skipped = None
            while len(frames) > 1 and (
                prefix == frames[-1].block.header_indentation
                or not prefix.startswith(frames[-1].block.header_indentation)
            ):
                close()
            active = frames[-1]
            accepted: list[tuple[int | CompiledBlock, LinePattern, tuple[str | None, ...]]] = []
            recognized = 0
            strict_recognized = False
            for index, pattern in enumerate(active.block.body):
                values = _values(pattern, content)
                if values is not None:
                    accepted.append((index, pattern, values))
                elif pattern.diagnostic.accepts(content):
                    recognized += 1
            for child in active.block.children:
                for pattern in child.headers:
                    values = _values(pattern, content)
                    if values is not None:
                        accepted.append((child, pattern, values))
                    elif child.kind == "record" or pattern.structural.groups(content) is None:
                        if pattern.diagnostic.accepts(content):
                            recognized += 1
                            strict_recognized |= child.kind == "record"
            if accepted or recognized:
                if prefix != active.block.indentation:
                    raise NativeError("INVALID_INDENTATION", line=number)
                if len(accepted) > 1 or (not accepted and recognized > 1 and not strict_recognized):
                    raise NativeError("AMBIGUOUS_MATCH", line=number)
                if not accepted:
                    raise NativeError("MALFORMED_LINE", line=number)
                owner, pattern, values = accepted[0]
                if isinstance(owner, CompiledBlock):
                    open_block(owner, pattern, values)
                else:
                    if owner in active.seen:
                        raise NativeError("DUPLICATE_CAPTURE", line=number)
                    active.seen.add(owner)
                    output_bytes += _store(active.data, pattern, values, budget)
            elif template.root.children:
                skipped = prefix
        if output_bytes > limits.max_output_bytes:
            raise NativeError("RESOURCE_LIMIT", line=number)
    while frames:
        close()
    if template.root.kind == "section":
        if not records:
            raise NativeError("MISSING_SECTION")
        return _freeze_json_document(records[0])
    return _freeze_json_document(records)
