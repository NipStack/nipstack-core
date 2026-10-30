"""Explicit, immutable Feature selections independent of Profile availability."""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Self

from .errors import NipStackCoreUsageError

_SEGMENT = re.compile(r"[a-z][a-z0-9_]*")


class FeatureSelectionKind(Enum):
    """The three explicit ways to select Features."""

    ALL = "all"
    MODES = "modes"
    FEATURES = "features"


@dataclass(frozen=True, slots=True, init=False)
class FeatureSelection:
    """An ordered, immutable selection created only through its factories.

    Identifiers are checked for syntax, not availability in a Profile. Selection
    order is preserved for equality and representation, not Action execution.

    Attributes:
        kind: Whether all Features, Modes, or individual Features are selected.
        values: Distinct identifiers in first-appearance order; empty only for ALL.

    Raises:
        TypeError: Direct construction is attempted instead of using a factory.
    """

    kind: FeatureSelectionKind
    values: tuple[str, ...]

    def __new__(cls) -> Self:
        raise TypeError("Use FeatureSelection.all(), .modes(), or .features().")

    @classmethod
    def all(cls) -> Self:
        """Explicitly select every Feature, with no selected values."""
        return cls._create(FeatureSelectionKind.ALL, ())

    @classmethod
    def modes(cls, *values: str) -> Self:
        """Select one or more Modes without checking Profile availability.

        Args:
            *values: Mode identifiers matching ASCII ``[a-z][a-z0-9_]*``.

        Raises:
            NipStackCoreUsageError: Values are empty, not strings, or malformed.
        """
        return cls._create(
            FeatureSelectionKind.MODES,
            _validate_values(FeatureSelectionKind.MODES, values),
        )

    @classmethod
    def features(cls, *values: str) -> Self:
        """Select one or more three-segment Feature IDs.

        Args:
            *values: IDs of the form ``<mode>.<group>.<feature>``, with each
                segment matching ASCII ``[a-z][a-z0-9_]*``.

        Raises:
            NipStackCoreUsageError: Values are empty, not strings, or malformed.
        """
        return cls._create(
            FeatureSelectionKind.FEATURES,
            _validate_values(FeatureSelectionKind.FEATURES, values),
        )

    @classmethod
    def _create(cls, kind: FeatureSelectionKind, values: tuple[str, ...]) -> Self:
        # Only factories reach this allocation, after establishing the invariants.
        selection = object.__new__(cls)
        object.__setattr__(selection, "kind", kind)
        object.__setattr__(selection, "values", values)
        return selection


def _validate_values(kind: FeatureSelectionKind, values: tuple[str, ...]) -> tuple[str, ...]:
    if not values:
        raise NipStackCoreUsageError(f"{kind.value}() requires at least one identifier.")

    segment_count = 3 if kind is FeatureSelectionKind.FEATURES else 1
    for position, value in enumerate(values, start=1):
        if not isinstance(value, str):
            raise NipStackCoreUsageError(f"{kind.value}() argument {position} must be a string.")
        segments = value.split(".")
        if len(segments) != segment_count or any(
            _SEGMENT.fullmatch(segment) is None for segment in segments
        ):
            raise NipStackCoreUsageError(
                f"{kind.value}() argument {position} must have {segment_count} "
                "dot-separated segment(s) matching ASCII [a-z][a-z0-9_]*."
            )

    return tuple(dict.fromkeys(values))
