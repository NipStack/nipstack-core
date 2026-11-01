"""Structured operational errors and nonfatal diagnostics, not exceptions."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from .errors import NipStackCoreUsageError
from .feature_selection import _matches_identifier

_TECHNICAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
_SCHEMA_KEYWORD = re.compile(r"[A-Za-z_$][A-Za-z0-9_$-]*")
_CONTEXT_KEYS = frozenset(
    {"action_id", "feature_id", "connector_id", "http_status", "schema_keyword", "cause_code"}
)


class ErrorCode(Enum):
    """The approved operational error vocabulary; diagnostic codes are separate."""

    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    PROFILE_INVALID = "PROFILE_INVALID"
    SELECTION_INVALID = "SELECTION_INVALID"
    TARGET_INVALID = "TARGET_INVALID"
    FINGERPRINT_MISMATCH = "FINGERPRINT_MISMATCH"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    CONNECTION_TIMEOUT = "CONNECTION_TIMEOUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    SESSION_SETUP_ERROR = "SESSION_SETUP_ERROR"
    OPERATION_TIMEOUT = "OPERATION_TIMEOUT"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    COMMAND_ERROR = "COMMAND_ERROR"
    API_ERROR = "API_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"
    DEPENDENCY_FAILED = "DEPENDENCY_FAILED"
    FEATURE_UNSUPPORTED = "FEATURE_UNSUPPORTED"
    EXECUTION_CONTROL_ERROR = "EXECUTION_CONTROL_ERROR"
    CANCELLED = "CANCELLED"
    CLEANUP_ERROR = "CLEANUP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorStage(Enum):
    """The stage at which an operational error or diagnostic originated."""

    PROFILE = "PROFILE"
    PLANNING = "PLANNING"
    CONNECTION = "CONNECTION"
    SESSION_SETUP = "SESSION_SETUP"
    FINGERPRINT = "FINGERPRINT"
    ACTION = "ACTION"
    PARSING = "PARSING"
    VALIDATION = "VALIDATION"
    CANCELLATION = "CANCELLATION"
    CLEANUP = "CLEANUP"
    INTERNAL = "INTERNAL"


class RetryHint(Enum):
    """Advisory retry information, never an automatic retry policy."""

    NEVER = "NEVER"
    MAY_RETRY = "MAY_RETRY"
    UNKNOWN = "UNKNOWN"


class DiagnosticCode(Enum):
    """The separate vocabulary for nonfatal diagnostics."""

    CLEANUP_FAILED = "CLEANUP_FAILED"
    EVENT_CALLBACK_FAILED = "EVENT_CALLBACK_FAILED"
    INSECURE_TRANSPORT = "INSECURE_TRANSPORT"


@dataclass(frozen=True, slots=True, init=False)
class NipStackCoreError:
    """A structured result value with a fixed message and bounded technical context.

    Context producers must vet identifiers: syntax cannot recognize a secret
    deliberately placed in a valid ID. No transport exception translation occurs.

    Raises:
        NipStackCoreUsageError: Enum types or context values are invalid.
    """

    code: ErrorCode
    stage: ErrorStage
    retry_hint: RetryHint
    context: Mapping[str, str | int] = field(repr=False)

    # Python uses None for unhashability; mypy models object.__hash__ as callable.
    __hash__ = None  # type: ignore[assignment]

    def __init__(
        self,
        *,
        code: ErrorCode,
        stage: ErrorStage,
        retry_hint: RetryHint = RetryHint.UNKNOWN,
        context: Mapping[str, str | int] | None = None,
    ) -> None:
        if not isinstance(code, ErrorCode):
            raise NipStackCoreUsageError("code must be an ErrorCode.")
        if not isinstance(stage, ErrorStage):
            raise NipStackCoreUsageError("stage must be an ErrorStage.")
        if not isinstance(retry_hint, RetryHint):
            raise NipStackCoreUsageError("retry_hint must be a RetryHint.")
        frozen_context = _freeze_context(context)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "retry_hint", retry_hint)
        object.__setattr__(self, "context", frozen_context)

    @property
    def message(self) -> str:
        return self.code.value.replace("_", " ").capitalize() + "."


@dataclass(frozen=True, slots=True, init=False)
class NipStackCoreDiagnostic:
    """A nonfatal structured value with no retry hint or free-form message input.

    Raises:
        NipStackCoreUsageError: Enum types or context values are invalid.
    """

    code: DiagnosticCode
    stage: ErrorStage
    context: Mapping[str, str | int] = field(repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __init__(
        self,
        *,
        code: DiagnosticCode,
        stage: ErrorStage,
        context: Mapping[str, str | int] | None = None,
    ) -> None:
        if not isinstance(code, DiagnosticCode):
            raise NipStackCoreUsageError("code must be a DiagnosticCode.")
        if not isinstance(stage, ErrorStage):
            raise NipStackCoreUsageError("stage must be an ErrorStage.")
        frozen_context = _freeze_context(context)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "context", frozen_context)

    @property
    def message(self) -> str:
        return self.code.value.replace("_", " ").capitalize() + "."


def _freeze_context(value: Mapping[str, str | int] | None) -> Mapping[str, str | int]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise NipStackCoreUsageError("context must be a mapping or None.")
    if len(value) > len(_CONTEXT_KEYS):
        raise NipStackCoreUsageError("context contains too many entries.")
    copied: dict[str, str | int] = {}
    for key, item in value.items():
        if not isinstance(key, str) or key not in _CONTEXT_KEYS:
            raise NipStackCoreUsageError("context contains an unsupported key.")
        if key == "http_status":
            if isinstance(item, bool) or not isinstance(item, int) or not 100 <= item <= 599:
                raise NipStackCoreUsageError(
                    "context http_status must be an integer from 100 to 599."
                )
        else:
            if not isinstance(item, str) or not item or len(item) > 128 or not item.isascii():
                raise NipStackCoreUsageError(
                    "context text must contain 1 to 128 ASCII technical characters."
                )
            if key == "feature_id":
                valid = _matches_identifier(item, 3)
            elif key == "schema_keyword":
                valid = _SCHEMA_KEYWORD.fullmatch(item) is not None
            elif key == "cause_code":
                valid = any(item == code.value for code in ErrorCode)
            else:
                valid = _TECHNICAL_ID.fullmatch(item) is not None
            if not valid:
                raise NipStackCoreUsageError(
                    "context text does not match the technical field syntax."
                )
        copied[key] = item
    return MappingProxyType(copied)
