"""JSON data types and private defensive freezing, not a serialization API."""

from collections.abc import Mapping
from math import isfinite
from types import MappingProxyType
from typing import TypeAlias

from .errors import NipStackCoreUsageError

JSONValue: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | Mapping[str, "JSONValue"]
    | list["JSONValue"]
    | tuple["JSONValue", ...]
)
JSONDocument: TypeAlias = Mapping[str, JSONValue] | list[JSONValue] | tuple[JSONValue, ...]

_MAX_JSON_DEPTH = 64


def _validate_json_string(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise NipStackCoreUsageError("JSON strings must contain valid Unicode scalar values.")


def _freeze_json_value(value: object) -> JSONValue:
    return _freeze_value(value, ancestors=set(), depth=0)


def _freeze_json_document(value: object) -> JSONDocument:
    if not isinstance(value, (Mapping, list, tuple)):
        raise NipStackCoreUsageError("Feature data must have a JSON object or array root.")
    frozen = _freeze_json_value(value)
    assert isinstance(frozen, (Mapping, tuple))
    return frozen


def _freeze_value(value: object, *, ancestors: set[int], depth: int) -> JSONValue:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        _validate_json_string(value)
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise NipStackCoreUsageError("JSON numbers must be finite.")
        return value
    if not isinstance(value, (Mapping, list, tuple)):
        raise NipStackCoreUsageError("JSON content contains an unsupported value type.")
    if depth >= _MAX_JSON_DEPTH:
        raise NipStackCoreUsageError("JSON content cannot exceed 64 container levels.")
    identity = id(value)
    if identity in ancestors:
        raise NipStackCoreUsageError("JSON content cannot contain cycles.")
    ancestors.add(identity)
    try:
        if isinstance(value, Mapping):
            copied: dict[str, JSONValue] = {}
            for key, child in value.items():
                if not isinstance(key, str):
                    raise NipStackCoreUsageError("JSON object keys must be strings.")
                _validate_json_string(key)
                copied[key] = _freeze_value(child, ancestors=ancestors, depth=depth + 1)
            return MappingProxyType(copied)
        return tuple(_freeze_value(child, ancestors=ancestors, depth=depth + 1) for child in value)
    finally:
        ancestors.remove(identity)
