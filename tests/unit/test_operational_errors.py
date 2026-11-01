"""Safe messages, bounded context and exact operational vocabularies."""

from collections.abc import Hashable
from dataclasses import FrozenInstanceError

import pytest

from nipstack_core import (
    DiagnosticCode,
    ErrorCode,
    ErrorStage,
    NipStackCoreDiagnostic,
    NipStackCoreError,
    NipStackCoreUsageError,
    RetryHint,
    SecretValue,
)

ERROR_CODES = {
    "PROFILE_NOT_FOUND",
    "PROFILE_INVALID",
    "SELECTION_INVALID",
    "TARGET_INVALID",
    "FINGERPRINT_MISMATCH",
    "AUTHENTICATION_ERROR",
    "CONNECTION_TIMEOUT",
    "CONNECTION_ERROR",
    "SESSION_SETUP_ERROR",
    "OPERATION_TIMEOUT",
    "RESOURCE_LIMIT_EXCEEDED",
    "COMMAND_ERROR",
    "API_ERROR",
    "PARSE_ERROR",
    "SCHEMA_VALIDATION_ERROR",
    "DEPENDENCY_FAILED",
    "FEATURE_UNSUPPORTED",
    "EXECUTION_CONTROL_ERROR",
    "CANCELLED",
    "CLEANUP_ERROR",
    "INTERNAL_ERROR",
}


def test_error_taxonomy_contains_no_speculative_additions() -> None:
    assert {code.name for code in ErrorCode} == ERROR_CODES
    assert {code.name for code in ErrorStage} == {
        "PROFILE",
        "PLANNING",
        "CONNECTION",
        "SESSION_SETUP",
        "FINGERPRINT",
        "ACTION",
        "PARSING",
        "VALIDATION",
        "CANCELLATION",
        "CLEANUP",
        "INTERNAL",
    }
    assert {code.name for code in DiagnosticCode} == {
        "CLEANUP_FAILED",
        "EVENT_CALLBACK_FAILED",
        "INSECURE_TRANSPORT",
    }
    assert {code.name for code in RetryHint} == {"NEVER", "MAY_RETRY", "UNKNOWN"}
    for enum in (ErrorCode, ErrorStage, RetryHint, DiagnosticCode):
        assert all(member.value == member.name for member in enum)
        assert all(not isinstance(member, str) for member in enum)


@pytest.mark.parametrize("code", list(ErrorCode))
def test_operational_error_messages_are_fixed_safe_and_not_exceptions(code: ErrorCode) -> None:
    value = NipStackCoreError(code=code, stage=ErrorStage.INTERNAL)
    contextual = NipStackCoreError(
        code=code, stage=ErrorStage.INTERNAL, context={"action_id": "SYNTHETIC_SECRET"}
    )
    assert value.message == contextual.message
    assert value.message.endswith(".")
    assert contextual.retry_hint is RetryHint.UNKNOWN
    assert not isinstance(value, BaseException)
    for display in (str(contextual), repr(contextual), contextual.message):
        assert "SYNTHETIC_SECRET" not in display
    assert value.context == {}
    with pytest.raises(TypeError):
        NipStackCoreError(code=code, stage=ErrorStage.INTERNAL, message="SYNTHETIC_SECRET")


@pytest.mark.parametrize("code", list(DiagnosticCode))
def test_diagnostics_have_fixed_messages_and_no_retry_hint(code: DiagnosticCode) -> None:
    value = NipStackCoreDiagnostic(
        code=code, stage=ErrorStage.CLEANUP, context={"connector_id": "SYNTHETIC_SECRET"}
    )
    assert value.message == NipStackCoreDiagnostic(code=code, stage=value.stage).message
    assert not isinstance(value, BaseException)
    assert not hasattr(value, "retry_hint")
    assert "SYNTHETIC_SECRET" not in str(value) + repr(value) + value.message
    with pytest.raises(TypeError):
        NipStackCoreDiagnostic(code=code, stage=value.stage, message="unsafe")


@pytest.fixture(params=[NipStackCoreError, NipStackCoreDiagnostic])
def constructor(request: pytest.FixtureRequest) -> type:
    return request.param


def make(constructor: type, **kwargs: object) -> object:
    code = (
        ErrorCode.INTERNAL_ERROR
        if constructor is NipStackCoreError
        else DiagnosticCode.CLEANUP_FAILED
    )
    return constructor(code=code, stage=ErrorStage.INTERNAL, **kwargs)


def test_context_is_flat_named_defensively_owned_and_immutable(constructor: type) -> None:
    context = {
        "action_id": "get:config-v1",
        "feature_id": "config.system.hostname",
        "connector_id": "http.v1",
        "http_status": 599,
        "schema_keyword": "$ref",
        "cause_code": "PARSE_ERROR",
    }
    value = make(constructor, context=context)
    assert value.context == context
    context["action_id"] = "changed"
    assert value.context["action_id"] == "get:config-v1"
    with pytest.raises(TypeError):
        value.context["action_id"] = "changed"
    assert make(constructor, context=None).context == {}


@pytest.mark.parametrize(
    "context",
    [
        "",
        [],
        1,
        {"unknown": "SYNTHETIC_SECRET"},
        {1: "not-string-key"},
        {"action_id": None},
        {"action_id": 1},
        {"action_id": True},
        {"action_id": SecretValue("SYNTHETIC_SECRET")},
        {"action_id": ["nested"]},
        {"action_id": ValueError("SYNTHETIC_SECRET")},
        {"action_id": {"nested": "secret"}},
        {"action_id": ""},
        {"action_id": "x" * 129},
        {"action_id": "é"},
        {"action_id": "line\nbreak"},
        {"action_id": "space separated"},
        {"action_id": "/command"},
        {"connector_id": "https://user:password@host/path"},
        {"schema_keyword": "property with spaces"},
        {"schema_keyword": "$ref\n"},
        {"feature_id": "only.two"},
        {"feature_id": "Upper.system.hostname"},
        {"feature_id": "a.b." + "c" * 125},
        {"cause_code": "CUSTOM_ERROR"},
        {"cause_code": ErrorCode.PARSE_ERROR},
        {"http_status": True},
        {"http_status": False},
        {"http_status": 99},
        {"http_status": 600},
        {"http_status": 200.0},
        {"http_status": "200"},
        {str(index): "value" for index in range(7)},
    ],
)
def test_context_rejects_unsafe_or_unapproved_metadata(constructor: type, context: object) -> None:
    with pytest.raises(NipStackCoreUsageError) as caught:
        make(constructor, context=context)
    assert "SYNTHETIC_SECRET" not in str(caught.value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("action_id", "x" * 128),
        ("connector_id", "X" * 128),
        ("feature_id", "a.b." + "c" * 124),
        ("schema_keyword", "$" + "k" * 127),
        ("http_status", 100),
        ("http_status", 599),
    ],
)
def test_context_limits_are_inclusive(constructor: type, key: str, value: str | int) -> None:
    assert make(constructor, context={key: value}).context[key] == value


def test_structured_values_are_frozen_slotted_equal_and_unhashable(constructor: type) -> None:
    value = make(constructor)
    assert value == make(constructor, context={})
    assert not isinstance(value, Hashable)
    assert not hasattr(value, "__dict__")
    with pytest.raises(TypeError):
        hash(value)
    with pytest.raises(FrozenInstanceError):
        value.stage = ErrorStage.ACTION
    with pytest.raises((FrozenInstanceError, TypeError)):
        value.message = "unsafe"
    with pytest.raises(TypeError):
        constructor(value.code, value.stage)


@pytest.mark.parametrize(
    "code,stage",
    [
        ("INTERNAL_ERROR", ErrorStage.INTERNAL),
        (None, ErrorStage.INTERNAL),
        (ErrorCode.INTERNAL_ERROR, "INTERNAL"),
        (ErrorCode.INTERNAL_ERROR, None),
        (DiagnosticCode.CLEANUP_FAILED, ErrorStage.INTERNAL),
    ],
)
def test_error_enum_types_are_not_coerced(code: object, stage: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        NipStackCoreError(code=code, stage=stage)


@pytest.mark.parametrize(
    "code,stage",
    [
        ("CLEANUP_FAILED", ErrorStage.CLEANUP),
        (None, ErrorStage.CLEANUP),
        (DiagnosticCode.CLEANUP_FAILED, "CLEANUP"),
        (DiagnosticCode.CLEANUP_FAILED, None),
        (ErrorCode.CLEANUP_ERROR, ErrorStage.CLEANUP),
    ],
)
def test_diagnostic_enum_types_are_not_coerced(code: object, stage: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        NipStackCoreDiagnostic(code=code, stage=stage)


@pytest.mark.parametrize("hint", ["NEVER", None, True, ErrorCode.INTERNAL_ERROR])
def test_retry_hint_is_an_enum_not_a_retry_implementation(hint: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        NipStackCoreError(code=ErrorCode.INTERNAL_ERROR, stage=ErrorStage.INTERNAL, retry_hint=hint)
    for valid in RetryHint:
        assert (
            NipStackCoreError(
                code=ErrorCode.API_ERROR, stage=ErrorStage.PROFILE, retry_hint=valid
            ).retry_hint
            is valid
        )
