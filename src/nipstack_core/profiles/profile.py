"""Internal Profile composition, not loading, cross-reference validation or activation."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from nipstack_core.contracts.connection_target import _validate_timeout
from nipstack_core.contracts.errors import NipStackCoreUsageError
from nipstack_core.contracts.feature_selection import _matches_identifier
from nipstack_core.contracts.identities import _validate_text

from .actions import (
    ActionDefinition,
    CLIActionDefinition,
    HTTPActionDefinition,
    _freeze_commands,
    _validate_token,
)
from .features import FeatureDefinition

_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileMetadata:
    """Explicit platform/access metadata, independent of Profile ID segments."""

    name: str = field(repr=False)
    vendor: str = field(repr=False)
    platform_id: str = field(repr=False)
    access_variant: str = field(repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _validate_text(self.name, "name")
        _validate_text(self.vendor, "vendor")
        _validate_segmented_id(self.platform_id, "platform_id")
        _validate_token(self.access_variant, "access_variant")


@dataclass(frozen=True, slots=True, kw_only=True)
class ConnectionDefinition:
    """Static primary transport knowledge, not runtime target/authentication.

    Driver and setup are SSH-only; an optional HTTP authentication selector
    contains no credentials. Missing/unknown selectors do not certify available
    capabilities. None timeouts mean absent defaults, never unlimited operation.

    Raises:
        NipStackCoreUsageError: Fields or transport-specific declarations are invalid.
    """

    connector: Literal["ssh", "http"]
    driver: str | None = field(default=None, repr=False)
    authentication: str | None = field(default=None, repr=False)
    session_setup: Sequence[str] = field(default=(), repr=False)
    connect_timeout: float | None = field(default=None, repr=False)
    operation_timeout: float | None = field(default=None, repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if not isinstance(self.connector, str) or self.connector not in ("ssh", "http"):
            raise NipStackCoreUsageError("connector must be exactly ssh or http.")
        if self.driver is not None:
            _validate_token(self.driver, "driver")
            if self.connector != "ssh":
                raise NipStackCoreUsageError("driver is only permitted for SSH.")
        if self.authentication is not None:
            _validate_token(self.authentication, "authentication")
            if self.connector != "http":
                raise NipStackCoreUsageError("authentication selector is only permitted for HTTP.")
        setup = _freeze_commands(self.session_setup, "session_setup")
        if self.connector == "http" and setup:
            raise NipStackCoreUsageError("session_setup is only permitted for SSH.")
        object.__setattr__(self, "session_setup", setup)
        object.__setattr__(
            self, "connect_timeout", _validate_timeout(self.connect_timeout, "connect_timeout")
        )
        object.__setattr__(
            self,
            "operation_timeout",
            _validate_timeout(self.operation_timeout, "operation_timeout"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class FingerprintDefinition:
    """Declared Action reference and criteria, without matching or compilation."""

    action_id: str = field(repr=False)
    include: Sequence[str] = field(repr=False)
    exclude: Sequence[str] = field(default=(), repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _validate_token(self.action_id, "action_id")
        include = _freeze_commands(self.include, "include")
        exclude = _freeze_commands(self.exclude, "exclude")
        if not include:
            raise NipStackCoreUsageError("include requires at least one criterion.")
        object.__setattr__(self, "include", include)
        object.__setattr__(self, "exclude", exclude)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileDefinition:
    """Preparatory typed data with local invariants, never an active Profile.

    Maps own their storage and check key/ID and transport/Action agreement.
    Empty maps and lexical unresolved references remain possible: resource
    loading, cross-reference completeness and activation belong to later gates.

    Raises:
        NipStackCoreUsageError: Local fields or composition invariants are invalid.
    """

    profile_id: str = field(repr=False)
    version: str = field(repr=False)
    metadata: ProfileMetadata = field(repr=False)
    connection: ConnectionDefinition = field(repr=False)
    actions: Mapping[str, ActionDefinition] = field(repr=False)
    features: Mapping[str, FeatureDefinition] = field(repr=False)
    spec_version: Literal[1] = 1
    fingerprint: FingerprintDefinition | None = field(default=None, repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _validate_segmented_id(self.profile_id, "profile_id")
        _validate_semver(self.version)
        if (
            isinstance(self.spec_version, bool)
            or not isinstance(self.spec_version, int)
            or self.spec_version != 1
        ):
            raise NipStackCoreUsageError("spec_version must be integer 1.")
        if not isinstance(self.metadata, ProfileMetadata):
            raise NipStackCoreUsageError("metadata must be a ProfileMetadata.")
        if not isinstance(self.connection, ConnectionDefinition):
            raise NipStackCoreUsageError("connection must be a ConnectionDefinition.")
        if self.fingerprint is not None and not isinstance(self.fingerprint, FingerprintDefinition):
            raise NipStackCoreUsageError("fingerprint must be a FingerprintDefinition or None.")
        if not isinstance(self.actions, Mapping) or not isinstance(self.features, Mapping):
            raise NipStackCoreUsageError("actions and features must be mappings.")
        actions: dict[str, ActionDefinition] = {}
        for key, action in self.actions.items():
            if not isinstance(key, str) or not isinstance(
                action, (CLIActionDefinition, HTTPActionDefinition)
            ):
                raise NipStackCoreUsageError("actions must map Action IDs to typed Actions.")
            if key != action.action_id:
                raise NipStackCoreUsageError("Action keys must equal their contained IDs.")
            if (self.connection.connector == "ssh") != isinstance(action, CLIActionDefinition):
                raise NipStackCoreUsageError("Action type must match the primary Connector.")
            actions[key] = action
        features: dict[str, FeatureDefinition] = {}
        for key, feature in self.features.items():
            if not isinstance(key, str) or not isinstance(feature, FeatureDefinition):
                raise NipStackCoreUsageError("features must map Feature IDs to FeatureDefinitions.")
            if key != feature.feature_id:
                raise NipStackCoreUsageError("Feature keys must equal their contained IDs.")
            features[key] = feature
        object.__setattr__(self, "actions", MappingProxyType(actions))
        object.__setattr__(self, "features", MappingProxyType(features))


def _validate_segmented_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not _matches_identifier(value, len(value.split("."))):
        raise NipStackCoreUsageError(f"{name} must have lowercase ASCII identifier segments.")


def _validate_semver(value: str) -> None:
    if not isinstance(value, str):
        raise NipStackCoreUsageError("version must follow SemVer 2.0.0.")
    match = _SEMVER.fullmatch(value)
    if match is None:
        raise NipStackCoreUsageError("version must follow SemVer 2.0.0.")
    prerelease = match.group(1)
    if prerelease is not None and any(
        len(identifier) > 1 and identifier.isdecimal() and identifier.startswith("0")
        for identifier in prerelease.split(".")
    ):
        raise NipStackCoreUsageError("numeric prerelease identifiers cannot have leading zeros.")
