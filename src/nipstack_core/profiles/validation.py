"""Pure preparatory checks and sanitized issues, not capability validation."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from nipstack_core.contracts.errors import NipStackCoreUsageError

from ._load_types import _MESSAGES as _LOAD_MESSAGES
from ._load_types import LoadedProfile, LoadErrorCode, ProfileLoadError
from .actions import CLIActionDefinition, HTTPActionDefinition
from .features import FeatureDefinition
from .profile import ProfileDefinition, _validate_segmented_id, _validate_semver

PreparationIssueCode: TypeAlias = Literal[
    "INVALID_CANDIDATE",
    "LOAD_FAILED",
    "INVALID_REFERENCE",
    "RESOURCE_MISSING",
    "DUPLICATE_PROFILE_ID",
]

_MESSAGES: Mapping[PreparationIssueCode, str] = {
    "INVALID_CANDIDATE": "A preparation candidate is malformed or unsupported.",
    "LOAD_FAILED": "A Profile candidate could not be loaded.",
    "INVALID_REFERENCE": "A Profile candidate references an unavailable Action.",
    "RESOURCE_MISSING": "A Profile candidate is missing a referenced resource snapshot.",
    "DUPLICATE_PROFILE_ID": "Multiple candidates declare the same Profile ID.",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparationIssue:
    """Fixed diagnostic data without source labels, exceptions or raw content."""

    code: PreparationIssueCode
    candidate_indices: tuple[int, ...]
    profile_id: str | None = field(default=None, repr=False)
    load_code: LoadErrorCode | None = None

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if type(self.code) is not str or self.code not in _MESSAGES:
            raise NipStackCoreUsageError("Preparation issue code is invalid.")
        if isinstance(self.candidate_indices, (str, bytes)) or not isinstance(
            self.candidate_indices, Sequence
        ):
            raise NipStackCoreUsageError("Candidate indices must be an ordered sequence.")
        indices = tuple(self.candidate_indices)
        if (
            not indices
            or any(type(index) is not int or index < 0 for index in indices)
            or any(left >= right for left, right in zip(indices, indices[1:], strict=False))
        ):
            raise NipStackCoreUsageError(
                "Candidate indices must be increasing nonnegative integers."
            )
        if self.profile_id is not None:
            _validate_segmented_id(self.profile_id, "profile_id")
        if self.code == "DUPLICATE_PROFILE_ID":
            if len(indices) < 2 or self.profile_id is None:
                raise NipStackCoreUsageError("A conflict requires multiple candidates and an ID.")
        elif len(indices) != 1:
            raise NipStackCoreUsageError("A local issue requires exactly one candidate index.")
        if self.code in ("INVALID_REFERENCE", "RESOURCE_MISSING") and self.profile_id is None:
            raise NipStackCoreUsageError("A structural issue requires a known Profile ID.")
        if self.code == "LOAD_FAILED":
            if (
                type(self.load_code) is not str
                or self.load_code not in _LOAD_MESSAGES
                or self.profile_id is not None
            ):
                raise NipStackCoreUsageError("A load issue requires a recognized code and no ID.")
        elif self.load_code is not None:
            raise NipStackCoreUsageError("Only a load issue can contain a load code.")
        object.__setattr__(self, "candidate_indices", indices)

    @property
    def message(self) -> str:
        return _MESSAGES[self.code]


def _project_load_failure(error: ProfileLoadError, index: int) -> PreparationIssue:
    code: object = getattr(error, "code", None)
    if type(code) is str:
        for known_code in _LOAD_MESSAGES:
            if code == known_code:
                return PreparationIssue(
                    code="LOAD_FAILED", candidate_indices=(index,), load_code=known_code
                )
    return PreparationIssue(code="INVALID_CANDIDATE", candidate_indices=(index,))


def _canonical_profile_id(loaded: LoadedProfile) -> str | None:
    definition = getattr(loaded, "definition", None)
    if not isinstance(definition, ProfileDefinition):
        return None
    profile_id = getattr(definition, "profile_id", None)
    version = getattr(definition, "version", None)
    if not isinstance(profile_id, str) or not isinstance(version, str):
        return None
    try:
        _validate_segmented_id(profile_id, "profile_id")
        _validate_semver(version)
    except NipStackCoreUsageError:
        return None
    return profile_id


def _check_action_references(definition: ProfileDefinition) -> None:
    for index, feature in enumerate(definition.features.values()):
        if any(action not in definition.actions for action in feature.inputs):
            raise ProfileLoadError("INVALID_REFERENCE", field=f"features[{index}].inputs")
    if (
        definition.fingerprint is not None
        and definition.fingerprint.action_id not in definition.actions
    ):
        raise ProfileLoadError("INVALID_REFERENCE", field="identification.action")


def _check_loaded_structure(loaded: LoadedProfile) -> PreparationIssueCode | None:
    definition = loaded.definition
    actions = getattr(definition, "actions", None)
    features = getattr(definition, "features", None)
    resources = getattr(loaded, "resources", None)
    if (
        not isinstance(actions, Mapping)
        or not isinstance(features, Mapping)
        or not isinstance(resources, Mapping)
        or not hasattr(definition, "fingerprint")
        or any(
            not isinstance(action, (CLIActionDefinition, HTTPActionDefinition))
            for action in actions.values()
        )
        or any(not isinstance(feature, FeatureDefinition) for feature in features.values())
        or any(
            not isinstance(key, str) or not isinstance(value, bytes)
            for key, value in resources.items()
        )
    ):
        return "INVALID_CANDIDATE"
    try:
        _check_action_references(definition)
    except ProfileLoadError as error:
        if error.code != "INVALID_REFERENCE":
            raise
        return "INVALID_REFERENCE"
    for feature in definition.features.values():
        if feature.parser.template not in resources or feature.schema not in resources:
            return "RESOURCE_MISSING"
    return None
