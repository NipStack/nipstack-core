"""One typed boundary for the official, untyped google-re2 binding."""

from dataclasses import dataclass, field
from importlib import import_module
from typing import Protocol, cast


class _Match(Protocol):
    def groups(self) -> tuple[str | None, ...]: ...


class _Pattern(Protocol):
    def fullmatch(self, text: str) -> _Match | None: ...


class _Options(Protocol):
    max_mem: int
    log_errors: bool


class _Binding(Protocol):
    error: type[Exception]

    def Options(self) -> _Options: ...

    def compile(self, expression: str, *, options: _Options) -> _Pattern: ...

    def escape(self, text: str) -> str: ...


# The dependency has no PEP 561 metadata. Keep its dynamic surface confined here.
_binding = cast(_Binding, import_module("re2"))


@dataclass(frozen=True, slots=True)
class Regex:
    _pattern: _Pattern = field(repr=False)

    @classmethod
    def compile(cls, expression: str, *, memory: int) -> "Regex | None":
        options = _binding.Options()
        options.max_mem = memory
        options.log_errors = False
        compiled = None
        try:
            compiled = _binding.compile(expression, options=options)
        except _binding.error:
            pass
        # Do not keep the upstream exception (which can include author text).
        return None if compiled is None else cls(compiled)

    def groups(self, text: str) -> tuple[str | None, ...] | None:
        matched = self._pattern.fullmatch(text)
        return None if matched is None else matched.groups()

    def accepts(self, text: str) -> bool:
        return self._pattern.fullmatch(text) is not None


def escape_literal(text: str) -> str:
    return _binding.escape(text)
