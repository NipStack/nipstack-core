"""Metadata-only events and static synchronous control protocol validation."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from inspect import Parameter, signature
from sys import float_info

import pytest
from mypy import api

from nipstack_core import (
    CollectionStatus,
    ErrorCode,
    EventKind,
    ExecutionControl,
    ExecutionEvent,
    FeatureStatus,
    NipStackCoreUsageError,
)

NOW = datetime(2026, 11, 2, tzinfo=UTC)


def event() -> ExecutionEvent:
    return ExecutionEvent(
        kind=EventKind.COLLECTION_STARTED, timestamp=NOW, collection_id="collection"
    )


def test_event_vocabulary_is_exact_and_uses_standard_enum_values() -> None:
    assert {kind.name for kind in EventKind} == {
        "COLLECTION_STARTED",
        "PLAN_READY",
        "SESSION_OPENED",
        "FINGERPRINT_FINISHED",
        "ACTION_STARTED",
        "ACTION_FINISHED",
        "SESSION_CLOSED",
        "FEATURE_STARTED",
        "FEATURE_FINISHED",
        "COLLECTION_FINISHED",
    }
    assert all(kind.value == kind.name and not isinstance(kind, str) for kind in EventKind)


@pytest.mark.parametrize("kind", list(EventKind))
def test_every_event_kind_accepts_optional_metadata_absence(kind: EventKind) -> None:
    value = replace(event(), kind=kind)
    for name in (
        "correlation_id",
        "profile_id",
        "action_id",
        "feature_id",
        "status",
        "error_code",
        "duration_ms",
    ):
        assert getattr(value, name) is None


@pytest.mark.parametrize("kind", list(EventKind))
@pytest.mark.parametrize("status", [*FeatureStatus, *CollectionStatus, None, "SUCCESS", True])
def test_only_terminal_events_accept_their_own_status_enum(kind: EventKind, status: object) -> None:
    valid = (
        status is None
        or kind is EventKind.FEATURE_FINISHED
        and isinstance(status, FeatureStatus)
        or kind is EventKind.COLLECTION_FINISHED
        and isinstance(status, CollectionStatus)
    )
    if valid:
        assert replace(event(), kind=kind, status=status).status is status
    else:
        with pytest.raises(NipStackCoreUsageError):
            replace(event(), kind=kind, status=status)


@pytest.mark.parametrize("field", ["collection_id", "correlation_id", "profile_id", "action_id"])
@pytest.mark.parametrize("value", [1, True, "", " leading", "trailing ", "a\nb", "\0", "\udfff"])
def test_opaque_event_ids_follow_20c_validation(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(event(), **{field: value})


@pytest.mark.parametrize(
    "value", [None, "", "only.two", "Upper.system.status", "check.system.status\n", 1]
)
def test_feature_id_uses_existing_syntax_when_supplied(value: object) -> None:
    if value is None:
        assert replace(event(), feature_id=value).feature_id is None
    else:
        with pytest.raises(NipStackCoreUsageError):
            replace(event(), feature_id=value)


def test_action_finish_does_not_invent_an_action_status() -> None:
    value = replace(
        event(),
        kind=EventKind.ACTION_FINISHED,
        action_id="opaque action",
        profile_id="vendor/model @ local",
        feature_id="check.system.status",
        error_code=ErrorCode.COMMAND_ERROR,
        duration_ms=0,
    )
    assert value.status is None
    assert value.action_id == "opaque action"
    assert type(value.duration_ms) is float
    for code in ErrorCode:
        assert replace(value, error_code=code).error_code is code


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "ACTION_STARTED"),
        ("kind", None),
        ("collection_id", None),
        ("error_code", "COMMAND_ERROR"),
        ("error_code", True),
        ("timestamp", NOW.replace(tzinfo=None)),
        ("timestamp", NOW.replace(tzinfo=timezone(timedelta(hours=1)))),
        ("timestamp", None),
        ("timestamp", "2026-11-02T00:00:00Z"),
    ],
)
def test_event_types_are_validated_without_coercion(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(event(), **{field: value})


def test_zero_offset_timezone_is_normalized_without_reading_a_clock() -> None:
    zero = timezone(timedelta(0), "zero")
    value = replace(event(), timestamp=NOW.replace(tzinfo=zero))
    assert value.timestamp == NOW
    assert value.timestamp.tzinfo is UTC


@pytest.mark.parametrize("duration", [None, 0, -0.0, 1, 0.25, float_info.max])
def test_event_duration_preserves_absence_and_normalizes_finite_numbers(
    duration: float | None,
) -> None:
    value = replace(event(), duration_ms=duration)
    assert value.duration_ms == duration
    if duration is not None:
        assert type(value.duration_ms) is float


@pytest.mark.parametrize(
    "duration", [True, False, "1", -1, float("nan"), float("inf"), float("-inf"), 10**1000]
)
def test_invalid_event_duration_fails_explicitly(duration: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(event(), duration_ms=duration)


def test_event_is_frozen_slotted_hashable_and_hides_opaque_metadata() -> None:
    value = replace(
        event(),
        collection_id="SYNTHETIC_COLLECTION",
        correlation_id="SYNTHETIC_CORRELATION",
        profile_id="SYNTHETIC_PROFILE",
        action_id="SYNTHETIC_ACTION",
        feature_id="synthetic.system.secret",
        kind=EventKind.FEATURE_FINISHED,
        status=FeatureStatus.FAILED,
        error_code=ErrorCode.PARSE_ERROR,
        duration_ms=1,
    )
    assert value == replace(value)
    assert hash(value) == hash(replace(value))
    assert not hasattr(value, "__dict__")
    for attribute in fields(value):
        with pytest.raises(FrozenInstanceError):
            setattr(value, attribute.name, None)
    for display in (repr(value), str(value), repr([value])):
        assert "SYNTHETIC" not in display
        assert "synthetic.system.secret" not in display
        assert "2026-" not in display
        assert "FEATURE_FINISHED" in display and "FAILED" in display and "PARSE_ERROR" in display
    for name in ("payload", "message", "context", "extra", "url", "command", "to_dict", "to_json"):
        assert not hasattr(value, name)


def test_event_errors_never_format_or_log_invalid_objects(caplog: pytest.LogCaptureFixture) -> None:
    class Unformattable:
        def __repr__(self) -> str:
            raise AssertionError("Do not display invalid inputs.")

        def __str__(self) -> str:
            raise AssertionError("Do not stringify invalid inputs.")

    for attribute in fields(event()):
        with pytest.raises(NipStackCoreUsageError):
            replace(event(), **{attribute.name: Unformattable()})
    assert not caplog.records


def test_event_signature_is_keyword_only_and_has_no_payload_input() -> None:
    assert all(
        parameter.kind is Parameter.KEYWORD_ONLY
        for parameter in signature(ExecutionEvent).parameters.values()
    )
    with pytest.raises(TypeError):
        ExecutionEvent()
    with pytest.raises(TypeError):
        ExecutionEvent(EventKind.COLLECTION_STARTED, NOW, "collection")
    with pytest.raises(TypeError):
        ExecutionEvent(
            kind=EventKind.COLLECTION_STARTED,
            timestamp=NOW,
            collection_id="collection",
            payload={"sensitive": "not-an-event-field"},
        )


def test_control_protocol_is_not_runtime_checkable_or_instantiable() -> None:
    with pytest.raises(TypeError):
        ExecutionControl()
    with pytest.raises(TypeError):
        isinstance(object(), ExecutionControl)


@pytest.mark.parametrize(
    "methods,valid",
    [
        (
            "def should_cancel(self) -> bool: ...\n    def on_event(self, event: ExecutionEvent) -> None: ...",
            True,
        ),
        ("def should_cancel(self) -> bool: ...", False),
        ("def on_event(self, event: ExecutionEvent) -> None: ...", False),
        (
            "def should_cancel(self) -> str: ...\n    def on_event(self, event: ExecutionEvent) -> None: ...",
            False,
        ),
        ("def should_cancel(self) -> bool: ...\n    def on_event(self) -> None: ...", False),
        (
            "def should_cancel(self) -> bool: ...\n    def on_event(self, event: ExecutionEvent) -> bool: ...",
            False,
        ),
        (
            "async def should_cancel(self) -> bool: ...\n    def on_event(self, event: ExecutionEvent) -> None: ...",
            False,
        ),
        (
            "def should_cancel(self) -> bool: ...\n    async def on_event(self, event: ExecutionEvent) -> None: ...",
            False,
        ),
    ],
)
def test_protocol_is_checked_statically_without_executing_callbacks(
    methods: str, valid: bool
) -> None:
    source = (
        "from nipstack_core import CollectionRequest, ConnectionTarget, ExecutionControl, "
        "ExecutionEvent, FeatureSelection\n"
        f"class Candidate:\n    {methods.replace(': ...', ': raise AssertionError()')}\n"
        "def compose(candidate: Candidate, target: ConnectionTarget) -> CollectionRequest:\n"
        "    control: ExecutionControl = candidate\n"
        "    return CollectionRequest(profile_id='synthetic', target=target,\n"
        "        selection=FeatureSelection.all(), execution_control=control)\n"
    )
    stdout, stderr, status = api.run(
        [
            "--config-file=/dev/null",
            "--strict",
            "--no-incremental",
            "--cache-dir=/dev/null",
            "--python-version=3.11",
            "-c",
            source,
        ]
    )
    if valid:
        assert status == 0, stdout + stderr
    else:
        assert status == 1 and stdout.count("error:") == 1 and "[assignment]" in stdout, (
            stdout + stderr
        )
