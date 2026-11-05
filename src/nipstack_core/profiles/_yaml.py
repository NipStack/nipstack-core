"""One-pass restricted YAML decoding; PyYAML alone owns YAML syntax parsing."""

import math
import re
import sys
from contextlib import closing
from dataclasses import dataclass

import yaml
from yaml.events import (
    AliasEvent,
    DocumentEndEvent,
    DocumentStartEvent,
    Event,
    MappingEndEvent,
    MappingStartEvent,
    ScalarEvent,
    SequenceEndEvent,
    SequenceStartEvent,
    StreamEndEvent,
    StreamStartEvent,
)

from nipstack_core.contracts.errors import NipStackCoreUsageError
from nipstack_core.contracts.json_data import JSONValue, _validate_json_string

from ._load_types import LoadErrorCode, LoadLimits, ProfileLoadError

_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_NONFINITE = re.compile(r"[+-]?\.(?:inf|nan)", re.IGNORECASE)


class _EventLoader(yaml.BaseLoader):
    """Reject directives before PyYAML silently discards unknown directive names."""

    def fetch_directive(self) -> None:
        mark = self.get_mark()
        raise ProfileLoadError("INVALID_YAML", line=mark.line + 1, column=mark.column + 1)


@dataclass(slots=True)
class _Frame:
    value: dict[str, JSONValue] | list[JSONValue]
    key: str | None = None


def _failure(event: Event, code: LoadErrorCode = "INVALID_YAML") -> ProfileLoadError:
    mark = event.start_mark
    return ProfileLoadError(
        code,
        line=None if mark is None else mark.line + 1,
        column=None if mark is None else mark.column + 1,
    )


def _scalar(event: ScalarEvent, limits: LoadLimits) -> JSONValue:
    text = event.value
    if len(text) > limits.max_scalar_bytes:
        raise _failure(event, "RESOURCE_LIMIT")
    try:
        _validate_json_string(text)
    except NipStackCoreUsageError:
        raise _failure(event) from None
    if len(text.encode("utf-8")) > limits.max_scalar_bytes:
        raise _failure(event, "RESOURCE_LIMIT")
    if event.style is not None:
        return text
    if not text or _NONFINITE.fullmatch(text):
        raise _failure(event)
    if text == "null":
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if _INTEGER.fullmatch(text):
        digits = len(text) - text.startswith("-")
        interpreter_limit = sys.get_int_max_str_digits()
        if digits > limits.max_integer_digits or (interpreter_limit and digits > interpreter_limit):
            raise _failure(event, "RESOURCE_LIMIT")
        return int(text, 10)
    if _NUMBER.fullmatch(text):
        number = float(text)
        if not math.isfinite(number):
            raise _failure(event)
        return number
    return text


def _append(frame: _Frame, value: JSONValue, event: Event) -> None:
    if isinstance(frame.value, list):
        frame.value.append(value)
    elif frame.key is None:
        if not isinstance(value, str) or not isinstance(event, ScalarEvent):
            raise _failure(event)
        if event.style is None and value == "<<":
            raise _failure(event)
        if value in frame.value:
            raise _failure(event)
        frame.key = value
    else:
        frame.value[frame.key] = value
        frame.key = None


def _decode_events(text: str, limits: LoadLimits) -> dict[str, JSONValue]:
    root: dict[str, JSONValue] | None = None
    stack: list[_Frame] = []
    documents = 0
    nodes = 0
    # Closing explicitly disposes PyYAML's generator even when a budget fails early.
    with closing(yaml.parse(text, Loader=_EventLoader)) as events:
        for event in events:
            if isinstance(event, DocumentStartEvent):
                documents += 1
                if documents != 1 or event.version is not None or event.tags:
                    raise _failure(event)
            elif isinstance(event, (ScalarEvent, MappingStartEvent, SequenceStartEvent)):
                if event.anchor is not None or event.tag is not None:
                    raise _failure(event)
                nodes += 1
                if nodes > limits.max_yaml_nodes:
                    raise _failure(event, "RESOURCE_LIMIT")
                if isinstance(event, ScalarEvent):
                    if not stack:
                        raise _failure(event)
                    _append(stack[-1], _scalar(event, limits), event)
                else:
                    if len(stack) >= limits.max_yaml_depth:
                        raise _failure(event, "RESOURCE_LIMIT")
                    container: dict[str, JSONValue] | list[JSONValue]
                    container = {} if isinstance(event, MappingStartEvent) else []
                    if stack:
                        _append(stack[-1], container, event)
                    elif root is None and isinstance(container, dict):
                        root = container
                    else:
                        raise _failure(event)
                    stack.append(_Frame(container))
            elif isinstance(event, (MappingEndEvent, SequenceEndEvent)):
                if not stack or stack[-1].key is not None:
                    raise _failure(event)
                stack.pop()
            elif isinstance(event, AliasEvent):
                raise _failure(event)
            elif not isinstance(event, (StreamStartEvent, StreamEndEvent, DocumentEndEvent)):
                raise _failure(event)
    if documents != 1 or root is None or stack:
        raise ProfileLoadError("INVALID_YAML")
    return root


def _decode_manifest_yaml(content: bytes, *, limits: LoadLimits) -> dict[str, JSONValue]:
    if len(content) > limits.max_manifest_bytes:
        raise ProfileLoadError("RESOURCE_LIMIT")
    text = _decode_utf8(content)
    if text.startswith("\ufeff"):
        raise ProfileLoadError("INVALID_YAML")
    try:
        return _decode_events(text, limits)
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark
        failure = ProfileLoadError(
            "INVALID_YAML",
            line=None if mark is None else mark.line + 1,
            column=None if mark is None else mark.column + 1,
        )
    except yaml.YAMLError:
        failure = ProfileLoadError("INVALID_YAML")
    raise failure


def _decode_utf8(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        failure = ProfileLoadError("INVALID_ENCODING")
    raise failure
