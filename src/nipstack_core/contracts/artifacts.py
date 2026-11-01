"""Successful acquisition artifacts and the vocabulary for future raw exposure."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .errors import NipStackCoreUsageError
from .feature_selection import _matches_identifier
from .identities import _validate_duration, _validate_text, _validate_utc
from .json_data import JSONValue, _freeze_json_value


class RawArtifactPolicy(Enum):
    """Raw exposure policy vocabulary; filtering and double opt-in are not implemented."""

    NONE = "NONE"
    PROFILE_DEFAULT = "PROFILE_DEFAULT"


@dataclass(frozen=True, slots=True, kw_only=True)
class RawArtifact:
    """Successful acquisition with preserved provenance and hidden-or-empty content.

    Kind is an open semantic identifier, not a content-format discriminator.
    None means intentionally hidden; empty strings/objects/arrays are real output.
    Intended display hides payload and opaque metadata; reflection is not safe.

    Raises:
        NipStackCoreUsageError: Metadata, content, timestamp or duration is invalid.
    """

    artifact_id: str = field(repr=False)
    action_id: str = field(repr=False)
    kind: str
    content_type: str = field(repr=False)
    content: JSONValue = field(repr=False)
    acquired_at: datetime = field(repr=False)
    duration_ms: float = field(repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _validate_text(self.artifact_id, "artifact_id")
        _validate_text(self.action_id, "action_id")
        if not isinstance(self.kind, str) or not _matches_identifier(self.kind, 1):
            raise NipStackCoreUsageError("kind must match ASCII [a-z][a-z0-9_]*.")
        _validate_text(self.content_type, "content_type")
        acquired = _validate_utc(self.acquired_at, "acquired_at")
        duration = _validate_duration(self.duration_ms)
        content = _freeze_json_value(self.content)
        object.__setattr__(self, "acquired_at", acquired)
        object.__setattr__(self, "duration_ms", duration)
        object.__setattr__(self, "content", content)
