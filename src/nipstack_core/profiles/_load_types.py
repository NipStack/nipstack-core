"""Internal loading budgets, sanitized failures and owned byte snapshots."""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Literal, TypeAlias

from nipstack_core.contracts.errors import NipStackCoreUsageError

from .profile import ProfileDefinition

LoadErrorCode: TypeAlias = Literal[
    "INVALID_ARGUMENT",
    "UNSUPPORTED_PLATFORM",
    "IO_ERROR",
    "INVALID_ENCODING",
    "INVALID_YAML",
    "INVALID_MANIFEST",
    "INVALID_REFERENCE",
    "UNSAFE_PATH",
    "RESOURCE_LIMIT",
    "RESOURCE_CHANGED",
]

_MESSAGES: Mapping[LoadErrorCode, str] = {
    "INVALID_ARGUMENT": "Profile loading arguments are invalid.",
    "UNSUPPORTED_PLATFORM": "Secure Profile loading requires supported Linux filesystem primitives.",
    "IO_ERROR": "A Profile file could not be accessed.",
    "INVALID_ENCODING": "The Profile manifest must use valid UTF-8.",
    "INVALID_YAML": "The Profile manifest contains unsupported or invalid YAML.",
    "INVALID_MANIFEST": "The Profile manifest does not match the supported grammar.",
    "INVALID_REFERENCE": "The Profile references an unavailable Action.",
    "UNSAFE_PATH": "A Profile path is unsafe or does not identify a regular file or directory.",
    "RESOURCE_LIMIT": "A Profile loading resource limit was exceeded.",
    "RESOURCE_CHANGED": "A Profile file changed during acquisition.",
}


class ProfileLoadError(NipStackCoreUsageError):
    """First loading failure, with technical metadata and no input interpolation.

    Field paths are supplied only by loader code, never by manifest keys or IDs.
    No original YAML/OS exception or source snippet is stored as error metadata.
    """

    def __init__(
        self,
        code: LoadErrorCode,
        *,
        field: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        self.code = code
        self.field = field
        self.line = line
        self.column = column
        super().__init__(_MESSAGES[code])


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadLimits:
    """Per-load positive integer budgets, controlled by the Python caller."""

    max_manifest_bytes: int = 1_048_576
    max_resource_bytes: int = 2_097_152
    max_total_bytes: int = 16_777_216
    max_yaml_depth: int = 80
    max_yaml_nodes: int = 100_000
    max_scalar_bytes: int = 65_536
    max_actions: int = 256
    max_features: int = 1_024
    max_resource_files: int = 2_048
    max_path_components: int = 32
    max_integer_digits: int = 512

    def __post_init__(self) -> None:
        for attribute in fields(self):
            value = getattr(self, attribute.name)
            if type(value) is not int or value <= 0:
                raise ProfileLoadError("INVALID_ARGUMENT", field=attribute.name)


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadedProfile:
    """Loaded definitions and opaque bytes, not a fully validated or active Profile."""

    definition: ProfileDefinition = field(repr=False)
    resources: Mapping[str, bytes] = field(repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if not isinstance(self.definition, ProfileDefinition) or not isinstance(
            self.resources, Mapping
        ):
            raise ProfileLoadError("INVALID_ARGUMENT")
        copied: dict[str, bytes] = {}
        for reference, content in self.resources.items():
            if not isinstance(reference, str) or not isinstance(content, bytes):
                raise ProfileLoadError("INVALID_ARGUMENT")
            copied[reference] = content
        object.__setattr__(self, "resources", MappingProxyType(copied))
