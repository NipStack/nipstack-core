"""Defensive JSON snapshots, including adversarial values and exact depth limits."""

from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType

import pytest

from nipstack_core import NipStackCoreUsageError, SecretValue
from nipstack_core.contracts.json_data import _freeze_json_document, _freeze_json_value


class UnsafeDisplay:
    def __repr__(self) -> str:
        raise AssertionError("Invalid input must not be formatted.")

    def __str__(self) -> str:
        raise AssertionError("Invalid input must not be converted to text.")


@pytest.mark.parametrize("value", [None, True, False, 0, 10**1000, 1.5, "", "é\n😀"])
def test_json_scalars_are_preserved(value: object) -> None:
    assert _freeze_json_value(value) == value


@pytest.mark.parametrize("value", [{}, [], (), {"empty": []}, [None, True, ""]])
def test_object_and_array_roots_include_legitimate_empty_documents(value: object) -> None:
    frozen = _freeze_json_document(value)
    assert isinstance(frozen, (Mapping, tuple))


@pytest.mark.parametrize("value", [None, True, 1, 0.0, "", "not-an-array", b"[]"])
def test_documents_reject_scalar_roots_including_strings(value: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="object or array"):
        _freeze_json_document(value)


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        b"raw",
        bytearray(b"raw"),
        {1, 2},
        datetime(2026, 1, 1, tzinfo=UTC),
        SecretValue("SYNTHETIC_SECRET"),
        ValueError("SYNTHETIC_SECRET"),
        UnsafeDisplay(),
    ],
)
def test_unsupported_content_is_rejected_without_formatting_it(value: object) -> None:
    for candidate in (value, {"nested": [value]}):
        with pytest.raises(NipStackCoreUsageError) as caught:
            _freeze_json_value(candidate)
        assert "SYNTHETIC_SECRET" not in str(caught.value)


@pytest.mark.parametrize("value", ["\ud800", "\udfff", "prefix\ud800suffix"])
def test_surrogates_are_rejected_in_values_and_keys(value: str) -> None:
    for candidate in (value, {"nested": value}, {value: "safe"}):
        with pytest.raises(NipStackCoreUsageError, match="Unicode"):
            _freeze_json_value(candidate)


@pytest.mark.parametrize("key", [1, None, False, ("key",), UnsafeDisplay()])
def test_object_keys_must_be_strings_without_echoing_them(key: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="keys must be strings"):
        _freeze_json_value({key: None})


def test_nested_snapshot_owns_every_mapping_and_array() -> None:
    nested = {"items": [{"value": "original"}]}
    source = {"nested": nested, "tuple": (nested,)}
    frozen = _freeze_json_document(MappingProxyType(source))
    nested["items"][0]["value"] = "changed"
    nested["items"].append({})
    source.clear()
    assert frozen == {
        "nested": {"items": ({"value": "original"},)},
        "tuple": ({"items": ({"value": "original"},)},),
    }
    with pytest.raises(TypeError):
        frozen["extra"] = "not mutable"
    with pytest.raises(TypeError):
        frozen["nested"]["items"][0]["value"] = "not mutable"
    assert isinstance(frozen["nested"]["items"], tuple)


def test_shared_noncyclic_subtrees_are_accepted_and_copied() -> None:
    shared = {"array": [1]}
    frozen = _freeze_json_value([shared, shared])
    assert frozen == ({"array": (1,)}, {"array": (1,)})
    assert frozen[0] is not frozen[1]
    shared["array"].append(2)
    assert frozen[0] == {"array": (1,)}


@pytest.mark.parametrize("kind", ["list", "dict", "mixed"])
def test_cycles_are_rejected(kind: str) -> None:
    value = []
    mapping = {}
    if kind == "list":
        value.append(value)
        root = value
    elif kind == "dict":
        mapping["self"] = mapping
        root = mapping
    else:
        mapping["array"] = value
        value.append(mapping)
        root = value
    with pytest.raises(NipStackCoreUsageError, match="cycles"):
        _freeze_json_value(root)


@pytest.mark.parametrize("container", [list, tuple, dict])
@pytest.mark.parametrize("depth", [63, 64, 65])
def test_depth_counts_containers_including_root(container: type, depth: int) -> None:
    value = None
    for _ in range(depth):
        value = {"item": value} if container is dict else container([value])
    if depth <= 64:
        _freeze_json_document(value)
    else:
        with pytest.raises(NipStackCoreUsageError, match="64"):
            _freeze_json_document(value)


def test_json_equality_is_structural_not_canonical_serialization() -> None:
    assert _freeze_json_value({"a": 1, "b": 2}) == _freeze_json_value({"b": 2, "a": 1})
    assert _freeze_json_value([1, 2]) != _freeze_json_value([2, 1])
