"""Internal immutable Native specifications and closed, sanitized failure codes."""

from dataclasses import dataclass, field, fields
from typing import Literal, TypeAlias

from nipstack_core.contracts.errors import NipStackCoreUsageError

from ._regex import Regex

NativeErrorCode: TypeAlias = Literal[
    "INVALID_ARGUMENT",
    "INVALID_ENCODING",
    "INVALID_TEMPLATE",
    "UNSUPPORTED_COMPOSITION",
    "INVALID_REGEX",
    "RESOURCE_LIMIT",
    "MISSING_SECTION",
    "DUPLICATE_SECTION",
    "MISSING_REQUIRED",
    "DUPLICATE_CAPTURE",
    "AMBIGUOUS_MATCH",
    "MALFORMED_LINE",
    "INVALID_INDENTATION",
]

_MESSAGES: dict[NativeErrorCode, str] = {
    "INVALID_ARGUMENT": "Native parser arguments are invalid.",
    "INVALID_ENCODING": "Native text must contain valid Unicode and supported line endings.",
    "INVALID_TEMPLATE": "The Native template does not match the supported grammar.",
    "UNSUPPORTED_COMPOSITION": "The capture composition has no supported deterministic boundaries.",
    "INVALID_REGEX": "A Native regex is invalid, unsupported or exceeds its compilation budget.",
    "RESOURCE_LIMIT": "A Native parser resource limit was exceeded.",
    "MISSING_SECTION": "The required root section was not found.",
    "DUPLICATE_SECTION": "The unique root section occurred more than once.",
    "MISSING_REQUIRED": "A required field pattern did not occur.",
    "DUPLICATE_CAPTURE": "A scalar capture occurred more than once in a block.",
    "AMBIGUOUS_MATCH": "More than one field pattern accepts the line.",
    "MALFORMED_LINE": "A declared line structure contains invalid capture content.",
    "INVALID_INDENTATION": "A declared body line has invalid indentation.",
}


class NativeError(NipStackCoreUsageError):
    """A fixed message and optional numeric line; no untrusted error metadata."""

    def __init__(self, code: NativeErrorCode, *, line: int | None = None) -> None:
        self.code = code
        self.line = line
        super().__init__(_MESSAGES[code])


@dataclass(frozen=True, slots=True, kw_only=True)
class NativeLimits:
    """Finite per-compilation and per-invocation budgets, not CPU/RSS guarantees."""

    max_template_bytes: int = 1_048_576
    max_input_bytes: int = 8_388_608
    max_lines: int = 100_000
    max_line_characters: int = 16_384
    max_patterns: int = 64
    max_captures: int = 128
    max_regex_bytes: int = 4_096
    max_re2_memory: int = 524_288
    max_records: int = 10_000
    max_output_bytes: int = 8_388_608

    def __post_init__(self) -> None:
        for attribute in fields(self):
            value = getattr(self, attribute.name)
            if type(value) is not int or value <= 0:
                raise NativeError("INVALID_ARGUMENT")
        if not 65_536 <= self.max_re2_memory <= 2_147_483_647:
            raise NativeError("INVALID_ARGUMENT")


@dataclass(frozen=True, slots=True)
class Capture:
    name: str = field(repr=False)
    mode: Literal["token", "rest", "regex"]
    optional: bool
    required: bool
    constraint: Regex | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class LinePattern:
    captures: tuple[Capture, ...] = field(repr=False)
    structural: Regex = field(repr=False)
    diagnostic: Regex = field(repr=False)
    required: bool


@dataclass(frozen=True, slots=True)
class CompiledNativeTemplate:
    """Internal prepared value; native handles and author text are not public contracts."""

    kind: Literal["section", "record"]
    header: LinePattern = field(repr=False)
    body: tuple[LinePattern, ...] = field(repr=False)
    indentation: str = field(repr=False)
    limits: NativeLimits
