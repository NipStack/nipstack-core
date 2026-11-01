"""Immutable Feature and Collection results with explicit local invariants."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from .artifacts import RawArtifact
from .connection_target import TargetDescriptor
from .errors import NipStackCoreUsageError
from .feature_selection import _matches_identifier
from .identities import (
    ExecutionMetadata,
    ProfileIdentity,
    SchemaIdentity,
    _validate_text,
    _validate_time_range,
)
from .json_data import JSONDocument, _freeze_json_document
from .operational_errors import ErrorCode, NipStackCoreDiagnostic, NipStackCoreError


class FeatureStatus(Enum):
    """The outcome of one resolved Feature, not an operational error reason."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ScopeHint(Enum):
    """Whether an observation describes its source or the system managed by it."""

    SOURCE = "SOURCE"
    MANAGED_SYSTEM = "MANAGED_SYSTEM"


class CollectionStatus(Enum):
    """Explicit Collection outcome, validated rather than inferred."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureResult:
    """One Feature outcome with immutable data and acquisition provenance.

    SUCCESS requires an object/array and schema identity. FAILED/SKIPPED require
    no data and a local structured reason; schema identity may be unavailable.
    Processing times describe local Feature processing, not network acquisition.

    Raises:
        NipStackCoreUsageError: Fields or status-dependent invariants are invalid.
    """

    feature_id: str = field(repr=False)
    status: FeatureStatus
    scope_hint: ScopeHint
    started_at: datetime = field(repr=False)
    finished_at: datetime = field(repr=False)
    schema_identity: SchemaIdentity | None = field(default=None, repr=False)
    data: JSONDocument | None = field(default=None, repr=False)
    error: NipStackCoreError | None = field(default=None, repr=False)
    source_artifact_refs: Sequence[str] = field(default=(), repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if not isinstance(self.feature_id, str) or not _matches_identifier(self.feature_id, 3):
            raise NipStackCoreUsageError(
                "feature_id must follow the three-segment Feature ID syntax."
            )
        if not isinstance(self.status, FeatureStatus):
            raise NipStackCoreUsageError("status must be a FeatureStatus.")
        if not isinstance(self.scope_hint, ScopeHint):
            raise NipStackCoreUsageError("scope_hint must be a ScopeHint.")
        if self.schema_identity is not None and not isinstance(
            self.schema_identity, SchemaIdentity
        ):
            raise NipStackCoreUsageError("schema_identity must be a SchemaIdentity or None.")
        if self.error is not None and not isinstance(self.error, NipStackCoreError):
            raise NipStackCoreUsageError("error must be a NipStackCoreError or None.")

        if self.status is FeatureStatus.SUCCESS:
            if self.error is not None or self.schema_identity is None:
                raise NipStackCoreUsageError("SUCCESS requires schema_identity and no local error.")
            frozen_data = _freeze_json_document(self.data)
        else:
            if self.data is not None or self.error is None:
                raise NipStackCoreUsageError("FAILED/SKIPPED require data=None and a local error.")
            frozen_data = None

        started, finished = _validate_time_range(self.started_at, self.finished_at)
        refs = _freeze_artifact_refs(self.source_artifact_refs)
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "finished_at", finished)
        object.__setattr__(self, "data", frozen_data)
        object.__setattr__(self, "source_artifact_refs", refs)


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionResult:
    """One target's declared outcome with immutable keyed results and diagnostics.

    Only the credential-free TargetDescriptor is accepted. No planning,
    acquisition, schema validation, raw filtering or public serialization occurs.

    Raises:
        NipStackCoreUsageError: Types, provenance, Profile version or status are incoherent.
    """

    status: CollectionStatus
    profile: ProfileIdentity = field(repr=False)
    target: TargetDescriptor = field(repr=False)
    execution: ExecutionMetadata = field(repr=False)
    features: Mapping[str, FeatureResult] = field(repr=False)
    artifacts: Mapping[str, RawArtifact] = field(repr=False)
    error: NipStackCoreError | None = field(default=None, repr=False)
    diagnostics: Sequence[NipStackCoreDiagnostic] = field(default=(), repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if not isinstance(self.status, CollectionStatus):
            raise NipStackCoreUsageError("status must be a CollectionStatus.")
        if not isinstance(self.profile, ProfileIdentity):
            raise NipStackCoreUsageError("profile must be a ProfileIdentity.")
        if not isinstance(self.target, TargetDescriptor):
            raise NipStackCoreUsageError("target must be a TargetDescriptor.")
        if not isinstance(self.execution, ExecutionMetadata):
            raise NipStackCoreUsageError("execution must be ExecutionMetadata.")
        if self.error is not None and not isinstance(self.error, NipStackCoreError):
            raise NipStackCoreUsageError("error must be a NipStackCoreError or None.")
        features = _freeze_features(self.features)
        artifacts = _freeze_artifacts(self.artifacts)
        if features and self.profile.version is None:
            raise NipStackCoreUsageError(
                "A Collection with FeatureResults requires a Profile version."
            )
        for result in features.values():
            if any(reference not in artifacts for reference in result.source_artifact_refs):
                raise NipStackCoreUsageError("Feature provenance refers to an absent artifact.")
        diagnostics = _freeze_diagnostics(self.diagnostics)
        _validate_collection_status(self.status, features, self.error)
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "diagnostics", diagnostics)


def _freeze_artifact_refs(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise NipStackCoreUsageError("source_artifact_refs must be a sequence of artifact IDs.")
    refs: list[str] = []
    seen: set[str] = set()
    for reference in value:
        _validate_text(reference, "source_artifact_ref")
        if reference in seen:
            raise NipStackCoreUsageError("source_artifact_refs cannot contain duplicates.")
        seen.add(reference)
        refs.append(reference)
    return tuple(refs)


def _freeze_features(value: Mapping[str, FeatureResult]) -> Mapping[str, FeatureResult]:
    if not isinstance(value, Mapping):
        raise NipStackCoreUsageError("features must be a mapping.")
    copied: dict[str, FeatureResult] = {}
    for key, result in value.items():
        if not isinstance(key, str) or not isinstance(result, FeatureResult):
            raise NipStackCoreUsageError("features must map Feature IDs to FeatureResults.")
        if key != result.feature_id:
            raise NipStackCoreUsageError("A features key must equal its FeatureResult.feature_id.")
        copied[key] = result
    return MappingProxyType(copied)


def _freeze_artifacts(value: Mapping[str, RawArtifact]) -> Mapping[str, RawArtifact]:
    if not isinstance(value, Mapping):
        raise NipStackCoreUsageError("artifacts must be a mapping.")
    copied: dict[str, RawArtifact] = {}
    for key, artifact in value.items():
        if not isinstance(key, str) or not isinstance(artifact, RawArtifact):
            raise NipStackCoreUsageError("artifacts must map artifact IDs to RawArtifacts.")
        if key != artifact.artifact_id:
            raise NipStackCoreUsageError("An artifacts key must equal its RawArtifact.artifact_id.")
        copied[key] = artifact
    return MappingProxyType(copied)


def _freeze_diagnostics(
    value: Sequence[NipStackCoreDiagnostic],
) -> tuple[NipStackCoreDiagnostic, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise NipStackCoreUsageError("diagnostics must be a sequence of NipStackCoreDiagnostics.")
    if any(not isinstance(item, NipStackCoreDiagnostic) for item in value):
        raise NipStackCoreUsageError("diagnostics must contain only NipStackCoreDiagnostics.")
    return tuple(value)


def _validate_collection_status(
    status: CollectionStatus,
    features: Mapping[str, FeatureResult],
    error: NipStackCoreError | None,
) -> None:
    if status is CollectionStatus.CANCELLED:
        if error is None or error.code is not ErrorCode.CANCELLED:
            raise NipStackCoreUsageError("CANCELLED requires a global CANCELLED error.")
        return
    if error is not None and error.code is ErrorCode.CANCELLED:
        raise NipStackCoreUsageError(
            "A global CANCELLED error requires CollectionStatus.CANCELLED."
        )
    successes = sum(result.status is FeatureStatus.SUCCESS for result in features.values())
    if status is CollectionStatus.SUCCESS:
        if not features or successes != len(features) or error is not None:
            raise NipStackCoreUsageError(
                "SUCCESS requires nonempty all-success Features and no global error."
            )
    elif status is CollectionStatus.PARTIAL:
        if not 0 < successes < len(features) or error is not None:
            raise NipStackCoreUsageError(
                "PARTIAL requires success and failure/skip, with no global error."
            )
    elif error is None and (not features or successes):
        raise NipStackCoreUsageError(
            "FAILED requires a global error or nonempty Features with only local failures/skips."
        )
