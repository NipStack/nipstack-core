"""Declared Profile/schema identity and execution metadata, without runtime I/O."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from sys import float_info
from typing import Literal

from .errors import NipStackCoreUsageError

_SCHEMA_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileIdentity:
    """The requested Profile ID and its version, if loading succeeded.

    A missing version permits early failure; it is not evidence of a loaded
    Profile. No registry lookup or version-format convention is imposed.

    Raises:
        NipStackCoreUsageError: An ID or supplied version is invalid.
    """

    profile_id: str = field(repr=False)
    version: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _validate_text(self.profile_id, "profile_id")
        if self.version is not None:
            _validate_text(self.version, "version")


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaIdentity:
    """Declared identity of JCS-canonicalized Schema content, not a computed hash.

    Identity is independent of Profiles and Features. Canonicalization and
    verification against actual Schema content belong to workstream 50D.

    Raises:
        NipStackCoreUsageError: Digest or algorithm values are invalid.
    """

    digest: str = field(repr=False)
    algorithm: Literal["schema-c14n-v1"] = "schema-c14n-v1"

    def __post_init__(self) -> None:
        if not isinstance(self.digest, str) or _SCHEMA_DIGEST.fullmatch(self.digest) is None:
            raise NipStackCoreUsageError(
                "digest must be sha256: followed by 64 lowercase hexadecimal characters."
            )
        if not isinstance(self.algorithm, str) or self.algorithm != "schema-c14n-v1":
            raise NipStackCoreUsageError("algorithm must be exactly schema-c14n-v1.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionMetadata:
    """Supplied execution identifiers, UTC timestamps and monotonic duration.

    No identifier, version or clock value is obtained automatically. Duration
    is validated independently of wall-clock timestamp differences.

    Raises:
        NipStackCoreUsageError: Text, timestamps or duration values are invalid.
    """

    collection_id: str = field(repr=False)
    nipstack_core_version: str = field(repr=False)
    started_at: datetime = field(repr=False)
    finished_at: datetime = field(repr=False)
    duration_ms: float = field(repr=False)
    correlation_id: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _validate_text(self.collection_id, "collection_id")
        _validate_text(self.nipstack_core_version, "nipstack_core_version")
        if self.correlation_id is not None:
            _validate_text(self.correlation_id, "correlation_id")
        started, finished = _validate_time_range(self.started_at, self.finished_at)
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "finished_at", finished)
        object.__setattr__(self, "duration_ms", _validate_duration(self.duration_ms))


def _validate_text(value: str, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(unicodedata.category(character) in ("Cc", "Cs") for character in value)
    ):
        raise NipStackCoreUsageError(
            f"{name} must be a nonempty string without peripheral whitespace "
            "or control/surrogate characters."
        )


def _validate_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise NipStackCoreUsageError(f"{name} must be a timezone-aware UTC datetime.")
    return value.astimezone(UTC)


def _validate_time_range(started_at: datetime, finished_at: datetime) -> tuple[datetime, datetime]:
    started = _validate_utc(started_at, "started_at")
    finished = _validate_utc(finished_at, "finished_at")
    if finished < started:
        raise NipStackCoreUsageError("finished_at must not precede started_at.")
    return started, finished


def _validate_duration(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= float_info.max
    ):
        raise NipStackCoreUsageError(
            "duration_ms must be finite nonnegative milliseconds representable as a float."
        )
    return float(value)
