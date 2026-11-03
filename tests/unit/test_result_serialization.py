"""Exact JSON result shape, independent snapshots and encoder-compatible integers."""

import builtins
import io
import json
import socket
import subprocess
import sys
import time
import traceback
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from nipstack_core import (
    BearerTokenAuth,
    CollectionRequest,
    CollectionResult,
    CollectionStatus,
    ConnectionTarget,
    DiagnosticCode,
    ErrorCode,
    ErrorStage,
    ExecutionEvent,
    ExecutionMetadata,
    FeatureResult,
    FeatureSelection,
    FeatureStatus,
    HTTPEndpoint,
    NipStackCoreDiagnostic,
    NipStackCoreError,
    NipStackCoreUsageError,
    ProfileIdentity,
    RawArtifact,
    RetryHint,
    SchemaIdentity,
    ScopeHint,
    SecretValue,
    SSHEndpoint,
    SSHKeyAuth,
    TargetDescriptor,
    UsernamePasswordAuth,
)
from nipstack_core.contracts.serialization import _copy_json_value

NOW = datetime(2026, 11, 2, tzinfo=UTC)
DIGEST = "sha256:a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0"


@pytest.fixture
def partial_result() -> CollectionResult:
    schema = SchemaIdentity(digest=DIGEST)
    artifact = RawArtifact(
        artifact_id="raw-1",
        action_id="read_system",
        kind="configuration_snapshot",
        content_type="text/plain",
        content=None,
        acquired_at=NOW + timedelta(milliseconds=5),
        duration_ms=1.5,
    )
    good = FeatureResult(
        feature_id="config.system.hostname",
        status=FeatureStatus.SUCCESS,
        scope_hint=ScopeHint.SOURCE,
        started_at=NOW + timedelta(milliseconds=6),
        finished_at=NOW + timedelta(milliseconds=7),
        schema_identity=schema,
        data={
            "hostname": "edge-lab",
            "interfaces": [{"name": "Ethernet1", "addresses": [], "enabled": True}],
            "note": None,
        },
        source_artifact_refs=["raw-1"],
    )
    bad = FeatureResult(
        feature_id="check.system.status",
        status=FeatureStatus.FAILED,
        scope_hint=ScopeHint.SOURCE,
        started_at=NOW + timedelta(milliseconds=8),
        finished_at=NOW + timedelta(milliseconds=9),
        error=NipStackCoreError(
            code=ErrorCode.PARSE_ERROR,
            stage=ErrorStage.PARSING,
            context={"action_id": "read_system"},
        ),
        source_artifact_refs=["raw-1"],
    )
    return CollectionResult(
        status=CollectionStatus.PARTIAL,
        profile=ProfileIdentity(profile_id="example.synthetic", version="1.0"),
        target=TargetDescriptor(scheme="ssh", host="switch.example.invalid", port=22),
        execution=ExecutionMetadata(
            collection_id="demo-20d",
            nipstack_core_version="0.1.0",
            started_at=NOW,
            finished_at=NOW + timedelta(milliseconds=20),
            duration_ms=20,
            correlation_id="demo-correlation",
        ),
        features={good.feature_id: good, bad.feature_id: bad},
        artifacts={"raw-1": artifact},
        diagnostics=[
            NipStackCoreDiagnostic(
                code=DiagnosticCode.CLEANUP_FAILED,
                stage=ErrorStage.CLEANUP,
                context={"connector_id": "ssh", "cause_code": "CLEANUP_ERROR"},
            )
        ],
    )


def test_complete_partial_output_is_exact_and_directly_json_encodable(
    partial_result: CollectionResult,
) -> None:
    expected = {
        "status": "PARTIAL",
        "profile": {"profile_id": "example.synthetic", "version": "1.0"},
        "target": {"scheme": "ssh", "host": "switch.example.invalid", "port": 22},
        "execution": {
            "collection_id": "demo-20d",
            "nipstack_core_version": "0.1.0",
            "started_at": "2026-11-02T00:00:00.000000Z",
            "finished_at": "2026-11-02T00:00:00.020000Z",
            "duration_ms": 20.0,
            "correlation_id": "demo-correlation",
        },
        "features": {
            "config.system.hostname": {
                "feature_id": "config.system.hostname",
                "status": "SUCCESS",
                "scope_hint": "SOURCE",
                "started_at": "2026-11-02T00:00:00.006000Z",
                "finished_at": "2026-11-02T00:00:00.007000Z",
                "schema_identity": {"digest": DIGEST, "algorithm": "schema-c14n-v1"},
                "data": {
                    "hostname": "edge-lab",
                    "interfaces": [{"name": "Ethernet1", "addresses": [], "enabled": True}],
                    "note": None,
                },
                "error": None,
                "source_artifact_refs": ["raw-1"],
            },
            "check.system.status": {
                "feature_id": "check.system.status",
                "status": "FAILED",
                "scope_hint": "SOURCE",
                "started_at": "2026-11-02T00:00:00.008000Z",
                "finished_at": "2026-11-02T00:00:00.009000Z",
                "schema_identity": None,
                "data": None,
                "error": {
                    "code": "PARSE_ERROR",
                    "stage": "PARSING",
                    "retry_hint": "UNKNOWN",
                    "context": {"action_id": "read_system"},
                    "message": "Parse error.",
                },
                "source_artifact_refs": ["raw-1"],
            },
        },
        "artifacts": {
            "raw-1": {
                "artifact_id": "raw-1",
                "action_id": "read_system",
                "kind": "configuration_snapshot",
                "content_type": "text/plain",
                "content": None,
                "acquired_at": "2026-11-02T00:00:00.005000Z",
                "duration_ms": 1.5,
            },
        },
        "error": None,
        "diagnostics": [
            {
                "code": "CLEANUP_FAILED",
                "stage": "CLEANUP",
                "context": {"connector_id": "ssh", "cause_code": "CLEANUP_ERROR"},
                "message": "Cleanup failed.",
            }
        ],
    }
    output = partial_result.to_dict()
    assert output == expected
    assert json.loads(json.dumps(output)) == expected
    assert json.loads(json.dumps(output, allow_nan=False)) == expected
    assert list(output) == [
        "status",
        "profile",
        "target",
        "execution",
        "features",
        "artifacts",
        "error",
        "diagnostics",
    ]
    assert list(output["features"]) == list(partial_result.features)


@pytest.mark.parametrize("status", list(CollectionStatus))
def test_all_collection_statuses_preserve_nulls_and_current_result_semantics(
    partial_result: CollectionResult,
    status: CollectionStatus,
) -> None:
    good, bad = partial_result.features.values()
    if status is CollectionStatus.SUCCESS:
        result = replace(partial_result, status=status, features={good.feature_id: good})
    elif status is CollectionStatus.FAILED:
        result = replace(partial_result, status=status, features={bad.feature_id: bad})
    elif status is CollectionStatus.CANCELLED:
        result = replace(
            partial_result,
            status=status,
            error=NipStackCoreError(code=ErrorCode.CANCELLED, stage=ErrorStage.CANCELLATION),
        )
    else:
        result = partial_result
    output = result.to_dict()
    assert output["status"] == status.value
    assert json.loads(json.dumps(output)) == output
    assert output["diagnostics"] and output["artifacts"]
    if status is CollectionStatus.CANCELLED:
        assert output["error"]["message"] == "Cancelled."
    else:
        assert output["error"] is None


@pytest.mark.parametrize(
    "status,code,stage",
    [
        (CollectionStatus.FAILED, ErrorCode.PROFILE_NOT_FOUND, ErrorStage.PROFILE),
        (CollectionStatus.CANCELLED, ErrorCode.CANCELLED, ErrorStage.CANCELLATION),
    ],
)
def test_early_failure_or_cancellation_has_complete_empty_maps(
    partial_result: CollectionResult,
    status: CollectionStatus,
    code: ErrorCode,
    stage: ErrorStage,
) -> None:
    result = replace(
        partial_result,
        status=status,
        profile=ProfileIdentity(profile_id="requested"),
        features={},
        artifacts={},
        diagnostics=[],
        execution=replace(partial_result.execution, correlation_id=None),
        error=NipStackCoreError(code=code, stage=stage),
    )
    output = result.to_dict()
    assert output["profile"] == {"profile_id": "requested", "version": None}
    assert output["features"] == output["artifacts"] == {}
    assert output["diagnostics"] == []
    assert output["execution"]["correlation_id"] is None
    assert output["error"]["context"] == {}
    assert output["error"]["code"] == code.value
    assert json.loads(json.dumps(output)) == output


@pytest.mark.parametrize("hint", list(RetryHint))
def test_global_error_and_successful_features_can_coexist_with_any_retry_hint(
    partial_result: CollectionResult,
    hint: RetryHint,
) -> None:
    good = next(iter(partial_result.features.values()))
    result = replace(
        partial_result,
        status=CollectionStatus.FAILED,
        features={good.feature_id: good},
        error=NipStackCoreError(
            code=ErrorCode.INTERNAL_ERROR, stage=ErrorStage.INTERNAL, retry_hint=hint
        ),
    )
    assert result.to_dict()["error"]["retry_hint"] == hint.value
    assert result.to_dict()["features"][good.feature_id]["status"] == "SUCCESS"


@pytest.mark.parametrize("data", [{}, [], (), {"nested": [None, False, 0, -1, 0.5, "", "é\n😀"]}])
def test_observation_shape_empty_values_and_unicode_are_preserved(
    partial_result: CollectionResult,
    data: object,
) -> None:
    good = replace(
        next(iter(partial_result.features.values())), data=data, scope_hint=ScopeHint.MANAGED_SYSTEM
    )
    output = replace(
        partial_result, status=CollectionStatus.SUCCESS, features={good.feature_id: good}
    ).to_dict()
    expected = [] if isinstance(data, tuple) else data
    assert output["features"][good.feature_id]["data"] == expected
    assert output["features"][good.feature_id]["scope_hint"] == "MANAGED_SYSTEM"
    assert json.loads(json.dumps(output, ensure_ascii=False)) == output


@pytest.mark.parametrize(
    "content", [None, "", {}, [], (), "SYNTHETIC_PRESENT_RAW", False, 0, {"nested": [1]}]
)
def test_raw_hidden_empty_and_deliberately_present_content_is_faithful(
    partial_result: CollectionResult,
    content: object,
) -> None:
    artifact = replace(partial_result.artifacts["raw-1"], content=content)
    output = replace(partial_result, artifacts={"raw-1": artifact}).to_dict()
    assert output["artifacts"]["raw-1"]["content"] == (
        [] if isinstance(content, tuple) else content
    )
    assert (output["artifacts"]["raw-1"]["content"] is None) is (content is None)
    assert json.loads(json.dumps(output)) == output


def test_output_allocates_only_independent_plain_json_containers(
    partial_result: CollectionResult,
) -> None:
    def containers(value: object) -> set[int]:
        if type(value) is dict:
            assert all(type(key) is str for key in value)
            return {id(value)}.union(*(containers(child) for child in value.values()))
        if type(value) is list:
            return {id(value)}.union(*(containers(child) for child in value))
        assert value is None or type(value) in (bool, int, float, str)
        return set()

    first = partial_result.to_dict()
    second = partial_result.to_dict()
    assert first == second
    assert not containers(first) & containers(second)
    good_id = "config.system.hostname"
    first["features"][good_id]["data"]["interfaces"][0]["addresses"].append("changed")
    first["features"][good_id]["source_artifact_refs"].clear()
    first["features"][good_id]["schema_identity"]["digest"] = "changed"
    first["features"]["check.system.status"]["error"]["context"].clear()
    first["diagnostics"][0]["context"].clear()
    first["profile"].clear()
    first["target"].clear()
    first["execution"].clear()
    first["artifacts"]["raw-1"]["content"] = "changed"
    assert partial_result.to_dict() == second
    assert partial_result.features[good_id].data["interfaces"][0]["addresses"] == ()
    assert partial_result.artifacts["raw-1"].content is None


def test_output_preserves_mapping_and_sequence_order(partial_result: CollectionResult) -> None:
    results = list(partial_result.features.values())
    observed = replace(results[0], source_artifact_refs=["second", "raw-1"])
    second = replace(partial_result.artifacts["raw-1"], artifact_id="second")
    result = replace(
        partial_result,
        features={results[1].feature_id: results[1], observed.feature_id: observed},
        artifacts={"second": second, "raw-1": partial_result.artifacts["raw-1"]},
        diagnostics=[*partial_result.diagnostics, *partial_result.diagnostics],
    )
    output = result.to_dict()
    assert list(output["features"]) == [results[1].feature_id, observed.feature_id]
    assert list(output["artifacts"]) == ["second", "raw-1"]
    assert output["features"][observed.feature_id]["source_artifact_refs"] == ["second", "raw-1"]
    assert len(output["diagnostics"]) == 2
    assert output["diagnostics"][0] is not output["diagnostics"][1]


def test_maximum_20c_payload_depth_is_not_reapplied_to_result_envelope(
    partial_result: CollectionResult,
) -> None:
    payload = 0
    for _ in range(64):
        payload = [payload]
    good = replace(next(iter(partial_result.features.values())), data=payload)
    artifact = replace(partial_result.artifacts["raw-1"], content=payload)
    result = replace(
        partial_result,
        status=CollectionStatus.SUCCESS,
        features={good.feature_id: good},
        artifacts={"raw-1": artifact},
    )
    output = result.to_dict()
    assert json.loads(json.dumps(output)) == output
    assert output["features"][good.feature_id]["data"] == payload
    assert output["artifacts"]["raw-1"]["content"] == payload
    with pytest.raises(NipStackCoreUsageError, match="64"):
        replace(good, data=[payload])


def test_timestamps_have_fixed_microsecond_utc_z_format(partial_result: CollectionResult) -> None:
    zero = timezone(timedelta(0), "zero")
    execution = replace(partial_result.execution, started_at=NOW.replace(tzinfo=zero))
    output = replace(partial_result, execution=execution).to_dict()
    assert output["execution"]["started_at"] == "2026-11-02T00:00:00.000000Z"
    assert output["execution"]["finished_at"] == "2026-11-02T00:00:00.020000Z"


@pytest.mark.parametrize("value", [0, -1, 2**63, 10**100, -(10**100)])
def test_ordinary_and_large_compatible_integers_remain_integers(
    partial_result: CollectionResult,
    value: int,
) -> None:
    good = replace(next(iter(partial_result.features.values())), data={"integer": value})
    artifact = replace(partial_result.artifacts["raw-1"], content=value)
    output = replace(
        partial_result,
        status=CollectionStatus.SUCCESS,
        features={good.feature_id: good},
        artifacts={"raw-1": artifact},
    ).to_dict()
    assert output["features"][good.feature_id]["data"]["integer"] == value
    assert type(output["artifacts"]["raw-1"]["content"]) is int
    assert json.loads(json.dumps(output)) == output


@pytest.mark.parametrize("sign", [1, -1])
def test_integer_encoder_limit_accepts_the_boundary_and_rejects_only_conversion_above_it(
    partial_result: CollectionResult,
    sign: int,
) -> None:
    limit = sys.get_int_max_str_digits()
    if limit == 0:
        pytest.skip(
            "This interpreter has no integer digit limit; isolated limits are tested separately."
        )
    compatible = sign * (10**limit - 1)
    incompatible = sign * 10**limit
    good = replace(next(iter(partial_result.features.values())), data={"integer": compatible})
    artifact = replace(partial_result.artifacts["raw-1"], content=compatible)
    valid = replace(
        partial_result,
        status=CollectionStatus.SUCCESS,
        features={good.feature_id: good},
        artifacts={"raw-1": artifact},
    )
    assert json.loads(json.dumps(valid.to_dict()))["artifacts"]["raw-1"]["content"] == compatible
    for invalid in (
        replace(
            valid, features={good.feature_id: replace(good, data={"SYNTHETIC_KEY": [incompatible]})}
        ),
        replace(valid, artifacts={"raw-1": replace(artifact, content=incompatible)}),
    ):
        with pytest.raises(NipStackCoreUsageError, match="integer.*standard JSON") as caught:
            invalid.to_dict()
        assert "SYNTHETIC" not in "".join(traceback.format_exception(caught.value))
        assert caught.value.__suppress_context__
    assert good.data["integer"] == compatible
    assert sys.get_int_max_str_digits() == limit


@pytest.mark.parametrize("limit", [0, 640])
def test_conversion_respects_isolated_encoder_settings_without_changing_them(limit: int) -> None:
    code = """
import json
import sys
from datetime import UTC, datetime
from nipstack_core import *
now = datetime(2026, 1, 1, tzinfo=UTC)
value = 10 ** 700
artifact = RawArtifact(artifact_id="raw", action_id="action", kind="snapshot",
    content_type="application/json", content=value, acquired_at=now, duration_ms=0)
result = CollectionResult(status=CollectionStatus.FAILED,
    profile=ProfileIdentity(profile_id="synthetic"),
    target=TargetDescriptor(scheme="ssh", host="example.invalid", port=22),
    execution=ExecutionMetadata(collection_id="id", nipstack_core_version="test",
        started_at=now, finished_at=now, duration_ms=0),
    features={}, artifacts={"raw": artifact},
    error=NipStackCoreError(code=ErrorCode.INTERNAL_ERROR, stage=ErrorStage.INTERNAL))
before = sys.get_int_max_str_digits()
try:
    output = result.to_dict()
except NipStackCoreUsageError:
    assert before == 640
else:
    assert before == 0 and json.loads(json.dumps(output))["artifacts"]["raw"]["content"] == value
assert sys.get_int_max_str_digits() == before
print("PASS")
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-X", f"int_max_str_digits={limit}", "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.stdout.strip() == "PASS"


def test_integer_subclass_display_hooks_are_not_called(partial_result: CollectionResult) -> None:
    class Integer(int):
        def __str__(self) -> str:
            raise AssertionError("Do not stringify integer subclasses.")

        def __repr__(self) -> str:
            raise AssertionError("Do not display integer subclasses.")

    artifact = replace(partial_result.artifacts["raw-1"], content=Integer(42))
    output = replace(partial_result, artifacts={"raw-1": artifact}).to_dict()
    assert json.loads(json.dumps(output))["artifacts"]["raw-1"]["content"] == 42


@pytest.mark.parametrize(
    "value",
    [
        SecretValue("SYNTHETIC_SECRET"),
        ValueError("SYNTHETIC_SECRET"),
        b"bytes",
        {1: "bad-key"},
        {1, 2},
        object(),
        float("nan"),
        float("inf"),
    ],
)
def test_unsupported_values_fail_without_input_coercion_or_echo(value: object) -> None:
    with pytest.raises(NipStackCoreUsageError) as caught:
        _copy_json_value(value)
    assert "SYNTHETIC" not in str(caught.value)


def test_nonfinite_invalid_unicode_and_timezone_values_are_already_blocked_by_20c(
    partial_result: CollectionResult,
) -> None:
    good = next(iter(partial_result.features.values()))
    for value in (float("nan"), float("inf"), "\udfff", SecretValue("SYNTHETIC_SECRET")):
        with pytest.raises(NipStackCoreUsageError):
            replace(good, data={"nested": [value]})
    for timestamp in (NOW.replace(tzinfo=None), NOW.replace(tzinfo=timezone(timedelta(hours=1)))):
        with pytest.raises(NipStackCoreUsageError):
            replace(partial_result.execution, started_at=timestamp)


def test_serialization_never_traverses_credentials_or_control_but_preserves_present_observations(
    partial_result: CollectionResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = "SYNTHETIC_PRIVATE_CREDENTIAL"
    observation = "SYNTHETIC_PRESENT_OBSERVATION"
    secret = SecretValue(credential)
    targets = [
        ConnectionTarget(
            endpoint=SSHEndpoint(host="example.invalid"),
            authentication=UsernamePasswordAuth(username=credential, password=secret),
        ),
        ConnectionTarget(
            endpoint=SSHEndpoint(host="example.invalid"),
            authentication=SSHKeyAuth(
                username=credential, key_file="/SYNTHETIC_PRIVATE_KEY", passphrase=secret
            ),
        ),
        ConnectionTarget(
            endpoint=HTTPEndpoint(host="example.invalid"),
            authentication=BearerTokenAuth(token=secret),
        ),
    ]

    class Control:
        def should_cancel(self) -> bool:
            raise AssertionError("Do not poll cancellation.")

        def on_event(self, event: ExecutionEvent) -> None:
            raise AssertionError("Do not dispatch callbacks.")

        def __repr__(self) -> str:
            raise AssertionError("Do not display control objects.")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Do not reveal credentials or change global settings.")

    monkeypatch.setattr(SecretValue, "reveal", forbidden)
    monkeypatch.setattr(sys, "set_int_max_str_digits", forbidden)
    for target in targets:
        request = CollectionRequest(
            profile_id="synthetic",
            target=target,
            selection=FeatureSelection.all(),
            execution_control=Control(),
        )
        good = replace(next(iter(partial_result.features.values())), data={"value": observation})
        artifact = replace(partial_result.artifacts["raw-1"], content=observation)
        result = replace(
            partial_result,
            target=request.target.to_descriptor(),
            status=CollectionStatus.SUCCESS,
            features={good.feature_id: good},
            artifacts={"raw-1": artifact},
        )
        rendered = json.dumps(result.to_dict())
        assert credential not in rendered
        assert "SYNTHETIC_PRIVATE_KEY" not in rendered
        assert observation in rendered
        assert result.artifacts["raw-1"].content == observation


def test_conversion_is_offline_without_ids_clocks_io_or_output_logging(
    partial_result: CollectionResult,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Serialization must not perform I/O or read runtime state.")

    with monkeypatch.context() as patched:
        for owner, name in (
            (builtins, "open"),
            (io, "open"),
            (Path, "stat"),
            (Path, "resolve"),
            (Path, "expanduser"),
            (socket, "socket"),
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (time, "time"),
            (time, "monotonic"),
            (uuid, "uuid4"),
        ):
            patched.setattr(owner, name, forbidden)
        assert partial_result.to_dict() == partial_result.to_dict()
    assert not caplog.records


def test_no_additional_public_serialization_routes_are_introduced(
    partial_result: CollectionResult,
) -> None:
    import nipstack_core

    assert isinstance(partial_result.features, Mapping)
    assert not hasattr(partial_result, "to_json")
    for name in ("result_to_dict", "serialize", "collect"):
        assert not hasattr(nipstack_core, name)
