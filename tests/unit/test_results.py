"""Feature/Collection coherence, provenance, redaction and offline boundaries."""

import builtins
import io
import socket
import time
import uuid
from collections.abc import Hashable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import nipstack_core
from nipstack_core import (
    CollectionResult,
    CollectionStatus,
    ConnectionTarget,
    DiagnosticCode,
    ErrorCode,
    ErrorStage,
    ExecutionMetadata,
    FeatureResult,
    FeatureStatus,
    NipStackCoreDiagnostic,
    NipStackCoreError,
    NipStackCoreUsageError,
    ProfileIdentity,
    RawArtifact,
    SchemaIdentity,
    ScopeHint,
    SecretValue,
    SSHEndpoint,
    TargetDescriptor,
    UsernamePasswordAuth,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SCHEMA = SchemaIdentity(digest="sha256:" + "a" * 64)
LOCAL_ERROR = NipStackCoreError(code=ErrorCode.PARSE_ERROR, stage=ErrorStage.PARSING)
GLOBAL_ERROR = NipStackCoreError(code=ErrorCode.INTERNAL_ERROR, stage=ErrorStage.INTERNAL)
CANCELLATION = NipStackCoreError(code=ErrorCode.CANCELLED, stage=ErrorStage.CANCELLATION)


def feature() -> FeatureResult:
    return FeatureResult(
        feature_id="config.system.hostname",
        status=FeatureStatus.SUCCESS,
        scope_hint=ScopeHint.SOURCE,
        started_at=NOW,
        finished_at=NOW,
        schema_identity=SCHEMA,
        data={},
    )


def raw() -> RawArtifact:
    return RawArtifact(
        artifact_id="artifact",
        action_id="action",
        kind="configuration_snapshot",
        content_type="text/plain",
        content=None,
        acquired_at=NOW,
        duration_ms=0,
    )


def collection() -> CollectionResult:
    result = feature()
    return CollectionResult(
        status=CollectionStatus.SUCCESS,
        profile=ProfileIdentity(profile_id="profile", version="version"),
        target=TargetDescriptor(scheme="ssh", host="example.invalid", port=22),
        execution=ExecutionMetadata(
            collection_id="collection",
            nipstack_core_version="development",
            started_at=NOW,
            finished_at=NOW,
            duration_ms=0,
        ),
        features={result.feature_id: result},
        artifacts={},
    )


def test_result_enums_are_standard_with_exact_vocabulary() -> None:
    assert {member.name for member in FeatureStatus} == {"SUCCESS", "FAILED", "SKIPPED"}
    assert {member.name for member in ScopeHint} == {"SOURCE", "MANAGED_SYSTEM"}
    assert {member.name for member in CollectionStatus} == {
        "SUCCESS",
        "PARTIAL",
        "FAILED",
        "CANCELLED",
    }
    for enum in (FeatureStatus, ScopeHint, CollectionStatus):
        assert all(member.value == member.name for member in enum)
        assert all(not isinstance(member, str) for member in enum)


@pytest.mark.parametrize("status", list(FeatureStatus))
@pytest.mark.parametrize("data", [None, {}, [], (), "", 1])
@pytest.mark.parametrize("schema", [None, SCHEMA])
@pytest.mark.parametrize("error", [None, LOCAL_ERROR])
def test_feature_status_matrix(
    status: FeatureStatus,
    data: object,
    schema: SchemaIdentity | None,
    error: NipStackCoreError | None,
) -> None:
    valid = (
        status is FeatureStatus.SUCCESS
        and isinstance(data, (dict, list, tuple))
        and schema is not None
        and error is None
    ) or (status is not FeatureStatus.SUCCESS and data is None and error is not None)
    if valid:
        value = replace(feature(), status=status, data=data, schema_identity=schema, error=error)
        assert value.status is status
        assert (value.data is None) is (data is None)
    else:
        with pytest.raises(NipStackCoreUsageError):
            replace(feature(), status=status, data=data, schema_identity=schema, error=error)


@pytest.mark.parametrize(
    "field,value",
    [
        ("feature_id", None),
        ("feature_id", "only.two"),
        ("feature_id", "Upper.system.name"),
        ("feature_id", "config.system.hostname\n"),
        ("status", "SUCCESS"),
        ("status", None),
        ("scope_hint", "SOURCE"),
        ("scope_hint", None),
        ("schema_identity", "digest"),
        ("error", ValueError("SYNTHETIC_SECRET")),
        ("started_at", NOW.replace(tzinfo=None)),
        ("finished_at", NOW - timedelta(microseconds=1)),
        ("data", {"nested": SecretValue("SYNTHETIC_SECRET")}),
    ],
)
def test_feature_types_and_validation_errors_do_not_echo_inputs(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError) as caught:
        replace(feature(), **{field: value})
    assert "SYNTHETIC_SECRET" not in str(caught.value)


def test_feature_data_and_refs_are_owned_ordered_and_immutable() -> None:
    data = {"SYNTHETIC_KEY": ["SYNTHETIC_DATA"]}
    refs = ["second", "first"]
    value = replace(feature(), data=data, source_artifact_refs=refs)
    data["SYNTHETIC_KEY"].clear()
    refs.clear()
    assert value.data == {"SYNTHETIC_KEY": ("SYNTHETIC_DATA",)}
    assert value.source_artifact_refs == ("second", "first")
    assert value != replace(value, source_artifact_refs=("first", "second"))
    with pytest.raises(TypeError):
        value.data["changed"] = True
    failed = replace(value, status=FeatureStatus.FAILED, data=None, error=LOCAL_ERROR)
    assert failed.source_artifact_refs == value.source_artifact_refs
    assert failed.schema_identity == SCHEMA
    skipped = replace(failed, status=FeatureStatus.SKIPPED, schema_identity=None)
    assert skipped.started_at == skipped.finished_at


@pytest.mark.parametrize(
    "refs",
    ["artifact", b"artifact", None, {"a"}, [None], [""], [" secret "], ["duplicate", "duplicate"]],
)
def test_source_refs_cannot_be_scalar_invalid_or_duplicate(refs: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(feature(), source_artifact_refs=refs)


S = FeatureStatus.SUCCESS
F = FeatureStatus.FAILED
K = FeatureStatus.SKIPPED


@pytest.mark.parametrize(
    "statuses,without_global",
    [
        ((), None),
        ((S,), CollectionStatus.SUCCESS),
        ((S, S), CollectionStatus.SUCCESS),
        ((F,), CollectionStatus.FAILED),
        ((K,), CollectionStatus.FAILED),
        ((F, K), CollectionStatus.FAILED),
        ((S, F), CollectionStatus.PARTIAL),
        ((S, K), CollectionStatus.PARTIAL),
        ((F, S, K), CollectionStatus.PARTIAL),
    ],
)
@pytest.mark.parametrize("error", [None, GLOBAL_ERROR, CANCELLATION])
@pytest.mark.parametrize("status", list(CollectionStatus))
def test_collection_status_matrix(
    statuses: tuple[FeatureStatus, ...],
    without_global: CollectionStatus | None,
    error: NipStackCoreError | None,
    status: CollectionStatus,
) -> None:
    results = {}
    for index, feature_status in enumerate(statuses):
        value = replace(feature(), feature_id=f"config.system.item_{index}")
        if feature_status is not S:
            value = replace(value, status=feature_status, data=None, error=LOCAL_ERROR)
        results[value.feature_id] = value
    allowed = (
        CollectionStatus.CANCELLED
        if error is CANCELLATION
        else CollectionStatus.FAILED
        if error is GLOBAL_ERROR
        else without_global
    )
    if status is allowed:
        value = replace(collection(), status=status, features=results, error=error)
        assert value.status is status
        assert len(value.features) == len(statuses)
    else:
        with pytest.raises(NipStackCoreUsageError):
            replace(collection(), status=status, features=results, error=error)


@pytest.mark.parametrize("status", list(CollectionStatus))
@pytest.mark.parametrize("feature_status", list(FeatureStatus))
def test_every_nonempty_feature_mapping_requires_profile_version(
    status: CollectionStatus,
    feature_status: FeatureStatus,
) -> None:
    value = feature()
    if feature_status is not S:
        value = replace(value, status=feature_status, data=None, error=LOCAL_ERROR)
    error = CANCELLATION if status is CollectionStatus.CANCELLED else GLOBAL_ERROR
    with pytest.raises(NipStackCoreUsageError, match="Profile version"):
        replace(
            collection(),
            profile=ProfileIdentity(profile_id="requested"),
            features={value.feature_id: value},
            status=status,
            error=error,
        )


@pytest.mark.parametrize("version", [None, "known"])
@pytest.mark.parametrize(
    "status,error",
    [
        (CollectionStatus.FAILED, GLOBAL_ERROR),
        (CollectionStatus.CANCELLED, CANCELLATION),
    ],
)
def test_empty_early_results_preserve_requested_profile_with_optional_version(
    version: str | None,
    status: CollectionStatus,
    error: NipStackCoreError,
) -> None:
    value = replace(
        collection(),
        features={},
        profile=ProfileIdentity(profile_id="requested", version=version),
        status=status,
        error=error,
    )
    assert value.profile.profile_id == "requested"
    assert value.features == {}


def test_same_schema_identity_can_be_shared_across_profiles_and_features() -> None:
    first = collection()
    second_feature = replace(feature(), feature_id="check.system.status")
    second = replace(
        first,
        profile=ProfileIdentity(profile_id="other", version="other-version"),
        features={second_feature.feature_id: second_feature},
    )
    assert next(iter(first.features.values())).schema_identity == second_feature.schema_identity
    assert first.profile != second.profile
    assert second_feature.feature_id in second.features


def test_masked_and_unreferenced_artifacts_are_preserved_with_owned_maps() -> None:
    observed = replace(feature(), source_artifact_refs=["artifact"])
    features = {observed.feature_id: observed}
    artifacts = {"artifact": raw(), "unreferenced": replace(raw(), artifact_id="unreferenced")}
    value = replace(collection(), features=features, artifacts=artifacts)
    features.clear()
    artifacts.clear()
    assert list(value.artifacts) == ["artifact", "unreferenced"]
    assert value.artifacts["artifact"].content is None
    assert value.features[observed.feature_id].source_artifact_refs == ("artifact",)
    with pytest.raises(TypeError):
        value.features["another"] = observed
    with pytest.raises(TypeError):
        value.artifacts["another"] = raw()
    cancelled = replace(value, status=CollectionStatus.CANCELLED, error=CANCELLATION)
    assert cancelled.artifacts == value.artifacts


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "SUCCESS"),
        ("profile", "profile"),
        ("target", "target"),
        ("execution", {}),
        ("error", ValueError("SYNTHETIC_SECRET")),
        ("features", []),
        ("features", {"wrong": feature()}),
        ("features", {feature().feature_id: raw()}),
        ("features", {1: feature()}),
        ("artifacts", []),
        ("artifacts", {"wrong": raw()}),
        ("artifacts", {"artifact": feature()}),
        ("artifacts", {1: raw()}),
        ("diagnostics", "diagnostic"),
        ("diagnostics", b"diagnostic"),
        ("diagnostics", None),
        ("diagnostics", [LOCAL_ERROR]),
        ("diagnostics", [ValueError("SYNTHETIC_SECRET")]),
    ],
)
def test_collection_rejects_bad_types_and_mismatched_map_keys(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError) as caught:
        replace(collection(), **{field: value})
    assert "SYNTHETIC_SECRET" not in str(caught.value)


def test_dangling_provenance_is_rejected_even_for_failed_features() -> None:
    for status in FeatureStatus:
        value = replace(feature(), source_artifact_refs=["absent"])
        if status is not S:
            value = replace(value, status=status, data=None, error=LOCAL_ERROR)
        with pytest.raises(NipStackCoreUsageError, match="absent artifact"):
            replace(collection(), features={value.feature_id: value})


@pytest.mark.parametrize("code", list(DiagnosticCode))
def test_diagnostics_do_not_downgrade_success_and_are_defensively_owned(
    code: DiagnosticCode,
) -> None:
    diagnostic = NipStackCoreDiagnostic(code=code, stage=ErrorStage.CLEANUP)
    source = [diagnostic, diagnostic]
    value = replace(collection(), diagnostics=source)
    source.clear()
    assert value.status is CollectionStatus.SUCCESS
    assert value.diagnostics == (diagnostic, diagnostic)
    assert value.error is None


@pytest.mark.parametrize("value", [feature(), collection()])
def test_results_are_frozen_slotted_structurally_equal_and_unhashable(value: object) -> None:
    assert value == replace(value)
    assert not isinstance(value, Hashable)
    assert not hasattr(value, "__dict__")
    with pytest.raises(TypeError):
        hash(value)
    with pytest.raises(FrozenInstanceError):
        value.status = "changed"
    assert not hasattr(value, "to_dict")
    with pytest.raises(TypeError):
        type(value)("value")


def test_mapping_order_is_preserved_but_equality_ignores_map_order() -> None:
    one = feature()
    two = replace(one, feature_id="check.system.status")
    first = replace(collection(), features={one.feature_id: one, two.feature_id: two})
    second = replace(first, features={two.feature_id: two, one.feature_id: one})
    assert list(first.features) == [one.feature_id, two.feature_id]
    assert list(second.features) == [two.feature_id, one.feature_id]
    assert first == second


def test_result_displays_never_expand_data_context_or_opaque_metadata() -> None:
    secret = "SYNTHETIC_SECRET"
    observed = replace(feature(), data={secret: [secret]}, source_artifact_refs=[secret])
    hidden = replace(raw(), artifact_id=secret, action_id=secret, content=secret)
    execution = replace(
        collection().execution,
        collection_id=secret,
        correlation_id=secret,
        nipstack_core_version=secret,
    )
    diagnostic = NipStackCoreDiagnostic(
        code=DiagnosticCode.CLEANUP_FAILED, stage=ErrorStage.CLEANUP, context={"action_id": secret}
    )
    result = replace(
        collection(),
        features={observed.feature_id: observed},
        artifacts={secret: hidden},
        profile=ProfileIdentity(profile_id=secret, version=secret),
        target=TargetDescriptor(scheme="ssh", host="secret.example.invalid", port=22),
        execution=execution,
        diagnostics=[diagnostic],
    )
    for value in (observed, hidden, execution, diagnostic, result):
        assert secret not in repr(value) + str(value)
    assert "secret.example.invalid" not in repr(result)
    assert "config.system.hostname" not in repr(result)
    assert "SUCCESS" in repr(result)
    target = ConnectionTarget(
        endpoint=SSHEndpoint(host="example.invalid"),
        authentication=UsernamePasswordAuth(username="user", password=SecretValue(secret)),
    )
    with pytest.raises(NipStackCoreUsageError, match="TargetDescriptor"):
        replace(result, target=target)


def test_result_construction_is_offline_and_does_not_read_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Result construction must be offline and deterministic.")

    with monkeypatch.context() as patched:
        for owner, name in (
            (builtins, "open"),
            (io, "open"),
            (Path, "stat"),
            (Path, "resolve"),
            (Path, "expanduser"),
            (socket, "socket"),
            (socket, "create_connection"),
            (time, "time"),
            (time, "monotonic"),
            (uuid, "uuid4"),
        ):
            patched.setattr(owner, name, forbidden)
        assert collection() == collection()
        assert raw() == raw()
        assert feature() == feature()
    for name in ("collect", "CollectionRequest", "ExecutionControl", "ProgressEvent"):
        assert not hasattr(nipstack_core, name)
