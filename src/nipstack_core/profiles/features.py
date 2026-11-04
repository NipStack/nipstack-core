"""Internal Feature/parser references, without resource reading or validation."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from nipstack_core.contracts.errors import NipStackCoreUsageError
from nipstack_core.contracts.feature_selection import _matches_identifier
from nipstack_core.contracts.identities import _validate_text

from .actions import _validate_token


@dataclass(frozen=True, slots=True, kw_only=True)
class ParserDefinition:
    """A V1 engine and lexical resource reference, not a compiled parser."""

    engine: Literal["native", "jmespath"]
    template: str = field(repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if not isinstance(self.engine, str) or self.engine not in ("native", "jmespath"):
            raise NipStackCoreUsageError("engine must be exactly native or jmespath.")
        _validate_resource_reference(self.template, "template")


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureDefinition:
    """Observation inputs and external resources, not a resolved or active Feature.

    Inputs are nonempty, ordered and unique. Existence, input compatibility,
    templates and schema contents are checked only by later approved gates.

    Raises:
        NipStackCoreUsageError: Feature syntax, inputs or resource references are invalid.
    """

    feature_id: str = field(repr=False)
    inputs: Sequence[str] = field(repr=False)
    parser: ParserDefinition = field(repr=False)
    schema: str = field(repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if not isinstance(self.feature_id, str) or not _matches_identifier(self.feature_id, 3):
            raise NipStackCoreUsageError(
                "feature_id must follow the three-segment Feature ID syntax."
            )
        if not isinstance(self.parser, ParserDefinition):
            raise NipStackCoreUsageError("parser must be a ParserDefinition.")
        _validate_resource_reference(self.schema, "schema")
        if isinstance(self.inputs, (str, bytes)) or not isinstance(self.inputs, Sequence):
            raise NipStackCoreUsageError("inputs must be a nonempty sequence of Action IDs.")
        inputs: list[str] = []
        seen: set[str] = set()
        for action_id in self.inputs:
            _validate_token(action_id, "input")
            if action_id in seen:
                raise NipStackCoreUsageError("inputs cannot contain duplicate Action IDs.")
            seen.add(action_id)
            inputs.append(action_id)
        if not inputs:
            raise NipStackCoreUsageError("inputs must be a nonempty sequence of Action IDs.")
        object.__setattr__(self, "inputs", tuple(inputs))


def _validate_resource_reference(value: str, name: str) -> None:
    _validate_text(value, name)
    if (
        value.startswith(("/", "~"))
        or any(character in value for character in ("\\", ":", "?", "#", "$"))
        or any(segment in ("", ".", "..") for segment in value.split("/"))
    ):
        raise NipStackCoreUsageError(f"{name} must be a relative POSIX resource reference.")
