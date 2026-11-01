"""Explicit secret values with masked display, not reflective-serialization safety."""

from dataclasses import dataclass, field

from .errors import NipStackCoreUsageError


@dataclass(frozen=True, slots=True, eq=False, init=False)
class SecretValue:
    """An immutable secret with identity equality and fixed masked display.

    Python introspection and reflective serialization can expose its private
    string. Neither access control nor physical memory zeroization is provided.

    Args:
        value: A nonempty string, preserved without trimming or conversion.

    Raises:
        NipStackCoreUsageError: The value is not a nonempty string.
    """

    _value: str = field(repr=False)

    def __init__(self, value: str, /) -> None:
        if not isinstance(value, str) or not value:
            raise NipStackCoreUsageError("SecretValue requires a nonempty string.")
        object.__setattr__(self, "_value", value)

    def __repr__(self) -> str:
        return "SecretValue('**********')"

    def __str__(self) -> str:
        return repr(self)

    def reveal(self) -> str:
        """Deliberately expose the secret for validation or a future Connector.

        Returns:
            The original string. Do not log, serialize or persist this value.
        """
        return self._value
