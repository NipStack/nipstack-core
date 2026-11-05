"""Immutable preparatory Profile sets; no active registry or promotion path."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, TypeAlias

from nipstack_core.contracts.errors import NipStackCoreUsageError
from nipstack_core.contracts.identities import _validate_text

from ._load_types import LoadedProfile, ProfileLoadError
from .validation import (
    PreparationIssue,
    _canonical_profile_id,
    _check_loaded_structure,
    _project_load_failure,
)

__all__ = ["PreparationInput", "PreparationLookup", "PreparedProfileSet"]

PreparationInput: TypeAlias = LoadedProfile | ProfileLoadError
PreparationLookupStatus: TypeAlias = Literal["PREPARED", "INVALID", "CONFLICT", "UNKNOWN"]
DeferredCheckCode: TypeAlias = Literal[
    "CONNECTOR_CAPABILITIES",
    "PARSER_TEMPLATE_VALIDATION",
    "PARSER_INPUT_COMPATIBILITY",
    "FINGERPRINT_SEMANTICS",
    "OBSERVATION_SCHEMA_VALIDATION",
    "SCHEMA_IDENTITY",
    "ACTIVATION_GATE",
]

_DEFERRED_CHECKS: tuple[DeferredCheckCode, ...] = (
    "CONNECTOR_CAPABILITIES",
    "PARSER_TEMPLATE_VALIDATION",
    "PARSER_INPUT_COMPATIBILITY",
    "FINGERPRINT_SEMANTICS",
    "OBSERVATION_SCHEMA_VALIDATION",
    "SCHEMA_IDENTITY",
    "ACTIVATION_GATE",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparationLookup:
    """Lookup data, never a capability assertion or an active Profile."""

    status: PreparationLookupStatus
    profile: LoadedProfile | None = field(default=None, repr=False)
    issues: tuple[PreparationIssue, ...] = ()

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in (
            "PREPARED",
            "INVALID",
            "CONFLICT",
            "UNKNOWN",
        ):
            raise NipStackCoreUsageError("Preparation lookup status is invalid.")
        if isinstance(self.issues, (str, bytes)) or not isinstance(self.issues, Sequence):
            raise NipStackCoreUsageError("Lookup issues must be a sequence of preparation issues.")
        issues = tuple(self.issues)
        if any(not isinstance(issue, PreparationIssue) for issue in issues):
            raise NipStackCoreUsageError("Lookup issues must contain preparation issues.")
        if self.status == "PREPARED":
            if not isinstance(self.profile, LoadedProfile) or issues:
                raise NipStackCoreUsageError("A prepared lookup requires a Profile and no issues.")
        elif self.profile is not None:
            raise NipStackCoreUsageError("Only a prepared lookup may contain a Profile.")
        if self.status in ("INVALID", "CONFLICT"):
            if not issues or any(issue.profile_id is None for issue in issues):
                raise NipStackCoreUsageError("A rejected lookup requires attributable issues.")
            if len({issue.profile_id for issue in issues}) != 1:
                raise NipStackCoreUsageError("Lookup issues must refer to one Profile ID.")
            conflict = any(issue.code == "DUPLICATE_PROFILE_ID" for issue in issues)
            if conflict != (self.status == "CONFLICT"):
                raise NipStackCoreUsageError("Lookup status must agree with conflict issues.")
        elif issues:
            raise NipStackCoreUsageError("Prepared and unknown lookups cannot contain issues.")
        object.__setattr__(self, "issues", issues)


@dataclass(frozen=True, slots=True, init=False)
class PreparedProfileSet:
    """Build a pure, immutable preparatory snapshot from explicit candidates.

    No input object proves secure-loader provenance. Preparation checks declared
    identity, references and resource presence, not parser/schema semantics,
    registered capabilities or activation. Deferred families are set-wide facts,
    not per-Profile applicability or successful validation.

    Args:
        candidates: Native list or tuple of loaded candidates and load errors.
            Mutable input variables should use list[PreparationInput]; a tuple
            also accepts covariant element types without consuming lazy inputs.

    Raises:
        NipStackCoreUsageError: The outer container is unsupported.
            Candidate failures instead become isolated preparation issues.
    """

    _profiles: Mapping[str, LoadedProfile] = field(repr=False)
    _issues: tuple[PreparationIssue, ...]
    _rejected: Mapping[str, tuple[PreparationIssue, ...]] = field(repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __init__(
        self, *, candidates: list[PreparationInput] | tuple[PreparationInput, ...]
    ) -> None:
        if type(candidates) not in (list, tuple):
            raise NipStackCoreUsageError("Preparation candidates must be a native list or tuple.")
        inputs = tuple(candidates)
        profiles: dict[str, LoadedProfile] = {}
        groups: dict[str, list[int]] = {}
        issues: list[PreparationIssue] = []
        for index, candidate in enumerate(inputs):
            if isinstance(candidate, ProfileLoadError):
                issues.append(_project_load_failure(candidate, index))
                continue
            if not isinstance(candidate, LoadedProfile):
                issues.append(
                    PreparationIssue(code="INVALID_CANDIDATE", candidate_indices=(index,))
                )
                continue
            profile_id = _canonical_profile_id(candidate)
            if profile_id is None:
                issues.append(
                    PreparationIssue(code="INVALID_CANDIDATE", candidate_indices=(index,))
                )
                continue
            code = _check_loaded_structure(candidate)
            if code == "INVALID_CANDIDATE":
                issues.append(PreparationIssue(code=code, candidate_indices=(index,)))
                continue
            groups.setdefault(profile_id, []).append(index)
            if code is None:
                profiles[profile_id] = candidate
            else:
                issues.append(
                    PreparationIssue(code=code, candidate_indices=(index,), profile_id=profile_id)
                )
        # Group before admission: invalid identifiable candidates still conflict.
        for profile_id, indices in groups.items():
            if len(indices) > 1:
                profiles.pop(profile_id, None)
                issues.append(
                    PreparationIssue(
                        code="DUPLICATE_PROFILE_ID",
                        candidate_indices=tuple(indices),
                        profile_id=profile_id,
                    )
                )
        rejected: dict[str, list[PreparationIssue]] = {}
        for issue in issues:
            if issue.profile_id is not None:
                rejected.setdefault(issue.profile_id, []).append(issue)
        object.__setattr__(
            self, "_profiles", MappingProxyType({key: profiles[key] for key in sorted(profiles)})
        )
        object.__setattr__(self, "_issues", tuple(issues))
        object.__setattr__(
            self,
            "_rejected",
            MappingProxyType({key: tuple(value) for key, value in rejected.items()}),
        )

    @property
    def profiles(self) -> Mapping[str, LoadedProfile]:
        return self._profiles

    @property
    def issues(self) -> tuple[PreparationIssue, ...]:
        return self._issues

    @property
    def deferred_checks(self) -> tuple[DeferredCheckCode, ...]:
        return _DEFERRED_CHECKS

    def lookup(self, profile_id: str) -> PreparationLookup:
        """Look up an exact opaque ID without normalization or global absence claims."""
        _validate_text(profile_id, "profile_id")
        profile = self._profiles.get(profile_id)
        if profile is not None:
            return PreparationLookup(status="PREPARED", profile=profile)
        issues = self._rejected.get(profile_id, ())
        if issues:
            if any(issue.code == "DUPLICATE_PROFILE_ID" for issue in issues):
                return PreparationLookup(status="CONFLICT", issues=issues)
            return PreparationLookup(status="INVALID", issues=issues)
        return PreparationLookup(status="UNKNOWN")
