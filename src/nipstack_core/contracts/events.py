"""Synchronous observation and execution-control contracts, without runtime behavior."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

from .errors import NipStackCoreUsageError
from .feature_selection import _matches_identifier
from .identities import _validate_duration, _validate_text, _validate_utc
from .operational_errors import ErrorCode
from .results import CollectionStatus, FeatureStatus


class EventKind(Enum):
    """The initial metadata-only execution observation vocabulary."""

    COLLECTION_STARTED = "COLLECTION_STARTED"
    PLAN_READY = "PLAN_READY"
    SESSION_OPENED = "SESSION_OPENED"
    FINGERPRINT_FINISHED = "FINGERPRINT_FINISHED"
    ACTION_STARTED = "ACTION_STARTED"
    ACTION_FINISHED = "ACTION_FINISHED"
    SESSION_CLOSED = "SESSION_CLOSED"
    FEATURE_STARTED = "FEATURE_STARTED"
    FEATURE_FINISHED = "FEATURE_FINISHED"
    COLLECTION_FINISHED = "COLLECTION_FINISHED"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionEvent:
    """An immutable metadata observation, not a runtime command or payload.

    Identifiers must be vetted by producers; syntax cannot detect a secret in
    an otherwise valid ID. Intended display omits IDs and timing metadata.
    A supplied status is FeatureStatus on FEATURE_FINISHED, CollectionStatus on
    COLLECTION_FINISHED, and forbidden otherwise. Optional metadata may be
    absent; construction does not prove the future runtime's lifecycle.

    Raises:
        NipStackCoreUsageError: Types, text, timestamp, status or duration are invalid.
    """

    kind: EventKind
    timestamp: datetime = field(repr=False)
    collection_id: str = field(repr=False)
    correlation_id: str | None = field(default=None, repr=False)
    profile_id: str | None = field(default=None, repr=False)
    action_id: str | None = field(default=None, repr=False)
    feature_id: str | None = field(default=None, repr=False)
    status: FeatureStatus | CollectionStatus | None = None
    error_code: ErrorCode | None = None
    duration_ms: float | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EventKind):
            raise NipStackCoreUsageError("kind must be an EventKind.")
        _validate_text(self.collection_id, "collection_id")
        for name, value in (
            ("correlation_id", self.correlation_id),
            ("profile_id", self.profile_id),
            ("action_id", self.action_id),
        ):
            if value is not None:
                _validate_text(value, name)
        if self.feature_id is not None and (
            not isinstance(self.feature_id, str) or not _matches_identifier(self.feature_id, 3)
        ):
            raise NipStackCoreUsageError(
                "feature_id must follow the three-segment Feature ID syntax or be None."
            )
        if self.error_code is not None and not isinstance(self.error_code, ErrorCode):
            raise NipStackCoreUsageError("error_code must be an ErrorCode or None.")
        if self.status is not None:
            if self.kind is EventKind.FEATURE_FINISHED:
                if not isinstance(self.status, FeatureStatus):
                    raise NipStackCoreUsageError("FEATURE_FINISHED status must be a FeatureStatus.")
            elif self.kind is EventKind.COLLECTION_FINISHED:
                if not isinstance(self.status, CollectionStatus):
                    raise NipStackCoreUsageError(
                        "COLLECTION_FINISHED status must be a CollectionStatus."
                    )
            else:
                raise NipStackCoreUsageError("status must be None for nonterminal event kinds.")
        timestamp = _validate_utc(self.timestamp, "timestamp")
        duration = None if self.duration_ms is None else _validate_duration(self.duration_ms)
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "duration_ms", duration)


class ExecutionControl(Protocol):
    """Structural synchronous control interface; no callbacks are invoked by contracts.

    There is no runtime shape check. Workstream 80 will own invocation at safe
    points: should_cancel failure stops further acquisition with
    EXECUTION_CONTROL_ERROR; on_event failure produces nonfatal
    EVENT_CALLBACK_FAILED and disables later callbacks. Cooperative cancellation
    cannot guarantee immediate interruption of blocking transport I/O.
    """

    def should_cancel(self) -> bool:
        """Report whether cooperative cancellation is requested."""
        ...

    def on_event(self, event: ExecutionEvent) -> None:
        """Consume an execution observation synchronously."""
        ...
