"""Successful raw acquisitions preserve masked, empty and visible content distinctly."""

from collections.abc import Hashable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from nipstack_core import NipStackCoreUsageError, RawArtifact, RawArtifactPolicy, SecretValue

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def artifact() -> RawArtifact:
    return RawArtifact(
        artifact_id="SYNTHETIC_ARTIFACT_ID",
        action_id="SYNTHETIC_ACTION_ID",
        kind="configuration_snapshot",
        content_type="text/plain",
        content=None,
        acquired_at=NOW,
        duration_ms=0,
    )


@pytest.mark.parametrize("content", [None, "", {}, [], (), "text", 0, False, 1.5, {"empty": []}])
def test_hidden_empty_and_visible_content_are_all_legal(content: object) -> None:
    value = replace(artifact(), content=content)
    assert (value.content is None) is (content is None)
    if isinstance(content, (list, tuple)):
        assert value.content == tuple(content)
    elif isinstance(content, dict):
        assert value.content == ({"empty": ()} if content else {})
    else:
        assert value.content == content


def test_kind_is_semantic_open_and_independent_of_content_format() -> None:
    for kind in ("configuration_snapshot", "inventory_document", "future_kind_2"):
        for content_type, content in (("text/plain", "text"), ("application/json", {"a": 1})):
            value = replace(artifact(), kind=kind, content_type=content_type, content=content)
            assert value.kind == kind
    assert replace(artifact(), content_type="application/vendor+json; version=1")
    assert replace(artifact(), artifact_id="same", action_id="same")
    assert artifact().duration_ms == 0.0
    assert type(artifact().duration_ms) is float
    assert {member.value for member in RawArtifactPolicy} == {"NONE", "PROFILE_DEFAULT"}
    assert all(not isinstance(member, str) for member in RawArtifactPolicy)


@pytest.mark.parametrize(
    "kind", [None, 1, "", "Upper", "two.words", "has-dash", "with space", "é", "x\n"]
)
def test_kind_has_minimal_ascii_token_validation(kind: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(artifact(), kind=kind)


@pytest.mark.parametrize("field", ["artifact_id", "action_id", "content_type"])
@pytest.mark.parametrize("value", [None, 1, "", " leading", "trailing ", "a\nb", "\udfff"])
def test_artifact_metadata_is_validated(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(artifact(), **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("acquired_at", NOW.replace(tzinfo=None)),
        ("acquired_at", NOW.replace(tzinfo=timezone(timedelta(hours=-1)))),
        ("acquired_at", "not-a-date"),
        ("duration_ms", True),
        ("duration_ms", -1),
        ("duration_ms", float("nan")),
        ("duration_ms", float("inf")),
        ("duration_ms", 10**1000),
        ("content", SecretValue("SYNTHETIC_SECRET")),
        ("content", b"raw"),
    ],
)
def test_invalid_acquisition_or_content_is_rejected(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError) as caught:
        replace(artifact(), **{field: value})
    assert "SYNTHETIC_SECRET" not in str(caught.value)


def test_artifacts_are_defensively_immutable_equal_unhashable_and_redacted() -> None:
    source = {"SYNTHETIC_KEY": ["SYNTHETIC_PAYLOAD"]}
    value = replace(artifact(), content=source)
    source["SYNTHETIC_KEY"].clear()
    assert value.content == {"SYNTHETIC_KEY": ("SYNTHETIC_PAYLOAD",)}
    assert value == replace(value)
    assert not isinstance(value, Hashable)
    assert not hasattr(value, "__dict__")
    with pytest.raises(TypeError):
        hash(value)
    with pytest.raises(TypeError):
        value.content["other"] = "changed"
    with pytest.raises(FrozenInstanceError):
        value.content = None
    for text in (
        "SYNTHETIC_ARTIFACT_ID",
        "SYNTHETIC_ACTION_ID",
        "SYNTHETIC_KEY",
        "SYNTHETIC_PAYLOAD",
    ):
        assert text not in str(value) + repr(value)
    assert "configuration_snapshot" in repr(value)


def test_artifact_requires_explicit_content_and_has_no_failure_or_extra_fields() -> None:
    with pytest.raises(TypeError):
        RawArtifact(
            artifact_id="a",
            action_id="b",
            kind="configuration_snapshot",
            content_type="text/plain",
            acquired_at=NOW,
            duration_ms=0,
        )
    with pytest.raises(TypeError):
        RawArtifact("a", "b", "configuration_snapshot", "text/plain", None, NOW, 0)
    for field in ("status", "error", "metadata", "headers", "command", "to_dict"):
        assert not hasattr(artifact(), field)
