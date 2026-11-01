"""Offline identities and explicitly supplied execution timing."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from sys import float_info

import pytest

from nipstack_core import (
    ExecutionMetadata,
    NipStackCoreUsageError,
    ProfileIdentity,
    SchemaIdentity,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def execution() -> ExecutionMetadata:
    return ExecutionMetadata(
        collection_id="opaque collection",
        nipstack_core_version="development version",
        started_at=NOW,
        finished_at=NOW,
        duration_ms=0,
    )


def test_profile_identity_preserves_opaque_ids_and_optional_versions() -> None:
    assert ProfileIdentity(profile_id="vendor/model @ local").version is None
    known = ProfileIdentity(profile_id="vendor/model @ local", version="not-semver")
    assert known.version == "not-semver"
    assert known == replace(known)
    assert hash(known) == hash(replace(known))


@pytest.mark.parametrize(
    "value", [None, 1, True, "", " leading", "trailing ", "a\nb", "\0", "\ud800"]
)
@pytest.mark.parametrize(
    "field", ["profile_id", "version", "collection_id", "nipstack_core_version", "correlation_id"]
)
def test_invalid_opaque_text_is_rejected(field: str, value: object) -> None:
    if value is None and field in ("version", "correlation_id"):
        return
    with pytest.raises(NipStackCoreUsageError):
        if field in ("profile_id", "version"):
            replace(ProfileIdentity(profile_id="valid"), **{field: value})
        else:
            replace(execution(), **{field: value})


def test_schema_identity_is_digest_only_and_hashable() -> None:
    identity = SchemaIdentity(digest="sha256:" + "a" * 64)
    assert identity.algorithm == "schema-c14n-v1"
    assert identity == SchemaIdentity(digest=identity.digest)
    assert hash(identity) == hash(SchemaIdentity(digest=identity.digest))
    assert not hasattr(identity, "profile")
    assert not hasattr(identity, "feature_id")
    with pytest.raises(TypeError):
        SchemaIdentity(digest=identity.digest, profile=ProfileIdentity(profile_id="other"))


@pytest.mark.parametrize(
    "digest",
    [
        None,
        1,
        "",
        "a" * 64,
        "sha256:" + "A" * 64,
        "sha256:" + "a" * 63,
        "sha256:" + "a" * 65,
        "sha512:" + "a" * 64,
        "sha256:" + "g" * 64,
        "sha256:" + "a" * 64 + "\n",
    ],
)
def test_digest_syntax_is_exact(digest: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        SchemaIdentity(digest=digest)


@pytest.mark.parametrize("algorithm", [None, 1, "", "schema-c14n-v2", "SCHEMA-C14N-V1"])
def test_algorithm_is_not_extensible_without_a_contract_change(algorithm: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        SchemaIdentity(digest="sha256:" + "a" * 64, algorithm=algorithm)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        1,
        "UTC",
        NOW.replace(tzinfo=None),
        NOW.replace(tzinfo=timezone(timedelta(hours=1))),
    ],
)
@pytest.mark.parametrize("field", ["started_at", "finished_at"])
def test_execution_requires_utc_aware_timestamps(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(execution(), **{field: value})


def test_utc_equivalents_are_normalized_and_time_order_is_checked() -> None:
    equivalent = NOW.replace(tzinfo=timezone(timedelta(0), "zero offset"))
    value = replace(execution(), started_at=equivalent, finished_at=equivalent)
    assert value.started_at.tzinfo is UTC
    assert value.finished_at.tzinfo is UTC
    with pytest.raises(NipStackCoreUsageError, match="precede"):
        replace(value, finished_at=NOW - timedelta(microseconds=1))
    independent = replace(value, finished_at=NOW + timedelta(days=1), duration_ms=0.25)
    assert independent.duration_ms == 0.25


@pytest.mark.parametrize("value", [0, -0.0, 1, 0.25, float_info.max])
def test_duration_is_finite_nonnegative_float(value: float) -> None:
    result = replace(execution(), duration_ms=value)
    assert result.duration_ms == value
    assert type(result.duration_ms) is float


@pytest.mark.parametrize(
    "value", [None, True, False, "1", -1, float("nan"), float("inf"), float("-inf"), 10**1000]
)
def test_invalid_duration_is_rejected_without_conversion_overflow(value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(execution(), duration_ms=value)


@pytest.mark.parametrize(
    "value",
    [
        ProfileIdentity(profile_id="profile", version="version"),
        SchemaIdentity(digest="sha256:" + "a" * 64),
        execution(),
    ],
)
def test_identity_values_are_frozen_slotted_hashable_and_redacted(value: object) -> None:
    assert value == replace(value)
    assert hash(value) == hash(replace(value))
    assert not hasattr(value, "__dict__")
    first_field = next(iter(value.__dataclass_fields__))
    with pytest.raises(FrozenInstanceError):
        setattr(value, first_field, "changed")
    display = str(value) + repr(value)
    for text in ("profile", "version", "sha256:", "opaque collection", "development version"):
        assert f"'{text}'" not in display


def test_execution_uses_only_the_approved_version_field() -> None:
    assert execution().nipstack_core_version == "development version"
    assert not hasattr(execution(), "core_version")
    with pytest.raises(TypeError):
        ExecutionMetadata(
            collection_id="id", core_version="v", started_at=NOW, finished_at=NOW, duration_ms=0
        )


def test_identity_constructors_are_keyword_only_and_require_explicit_inputs() -> None:
    for constructor in (ProfileIdentity, SchemaIdentity, ExecutionMetadata):
        with pytest.raises(TypeError):
            constructor()
        with pytest.raises(TypeError):
            constructor("value")
