"""Internal declarative acquisitions, without request encoding or transport."""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, TypeAlias

from nipstack_core.contracts.connection_target import _validate_timeout
from nipstack_core.contracts.errors import NipStackCoreUsageError
from nipstack_core.contracts.feature_selection import _matches_identifier
from nipstack_core.contracts.identities import _validate_text
from nipstack_core.contracts.json_data import JSONDocument, _freeze_json_value

_HEADER_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_PATH_CHARACTERS = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=:@/%-]*")
_HEX_PAIR = re.compile(r"[0-9A-Fa-f]{2}")
# Extending this technical allowlist requires a reviewed, non-authentication use case.
_TECHNICAL_HEADERS = frozenset({"accept", "content-type"})


@dataclass(frozen=True, slots=True, kw_only=True)
class ArtifactDefinition:
    """Semantic acquisition metadata, not permission to disclose raw content.

    Raises:
        NipStackCoreUsageError: Kind or exposure declaration is invalid.
    """

    kind: str
    expose_by_default: bool = False

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _validate_token(self.kind, "kind")
        if not isinstance(self.expose_by_default, bool):
            raise NipStackCoreUsageError("expose_by_default must be a bool.")


@dataclass(frozen=True, slots=True, kw_only=True)
class CLIContextDefinition:
    """Ordered static Action context commands; neither sequence is executed."""

    enter: Sequence[str] = field(default=(), repr=False)
    exit: Sequence[str] = field(default=(), repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "enter", _freeze_commands(self.enter, "enter"))
        object.__setattr__(self, "exit", _freeze_commands(self.exit, "exit"))


@dataclass(frozen=True, slots=True, kw_only=True)
class CLIActionDefinition:
    """One static CLI acquisition, independent of Feature selection or execution.

    Raises:
        NipStackCoreUsageError: Fields or optional timeout are invalid.
    """

    action_id: str = field(repr=False)
    command: str = field(repr=False)
    artifact: ArtifactDefinition = field(repr=False)
    context: CLIContextDefinition | None = field(default=None, repr=False)
    operation_timeout: float | None = field(default=None, repr=False)
    type: Literal["cli"] = field(default="cli", init=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _validate_token(self.action_id, "action_id")
        _validate_text(self.command, "command")
        if not isinstance(self.artifact, ArtifactDefinition):
            raise NipStackCoreUsageError("artifact must be an ArtifactDefinition.")
        if self.context is not None and not isinstance(self.context, CLIContextDefinition):
            raise NipStackCoreUsageError("context must be a CLIContextDefinition or None.")
        object.__setattr__(
            self,
            "operation_timeout",
            _validate_timeout(self.operation_timeout, "operation_timeout"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class HTTPRequestDefinition:
    """Static GET/POST data, not an encoded request or a read-only guarantee.

    Query pairs are raw strings, preserving order and repetitions. GET forbids
    a body; POST accepts an optional object/array with the existing JSON rules.
    No encoding, byte budgets, origin resolution or authentication occurs.

    Raises:
        NipStackCoreUsageError: Request structure or declarative values are invalid.
    """

    path: str = field(repr=False)
    method: Literal["GET", "POST"] = "GET"
    query: Sequence[tuple[str, str]] | None = field(default=None, repr=False)
    headers: Mapping[str, str] | None = field(default=None, repr=False)
    body: JSONDocument | None = field(default=None, repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _validate_http_path(self.path)
        if not isinstance(self.method, str) or self.method not in ("GET", "POST"):
            raise NipStackCoreUsageError("method must be exactly GET or POST.")
        if self.method == "GET" and self.body is not None:
            raise NipStackCoreUsageError("GET requires body=None.")
        query = _freeze_query(self.query)
        headers = _freeze_headers(self.headers)
        body = _freeze_body(self.body)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "headers", headers)
        object.__setattr__(self, "body", body)


@dataclass(frozen=True, slots=True, kw_only=True)
class HTTPActionDefinition:
    """One static HTTP acquisition; method alone does not establish its safety."""

    action_id: str = field(repr=False)
    request: HTTPRequestDefinition = field(repr=False)
    artifact: ArtifactDefinition = field(repr=False)
    operation_timeout: float | None = field(default=None, repr=False)
    type: Literal["http"] = field(default="http", init=False)

    __hash__ = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _validate_token(self.action_id, "action_id")
        if not isinstance(self.request, HTTPRequestDefinition):
            raise NipStackCoreUsageError("request must be an HTTPRequestDefinition.")
        if not isinstance(self.artifact, ArtifactDefinition):
            raise NipStackCoreUsageError("artifact must be an ArtifactDefinition.")
        object.__setattr__(
            self,
            "operation_timeout",
            _validate_timeout(self.operation_timeout, "operation_timeout"),
        )


ActionDefinition: TypeAlias = CLIActionDefinition | HTTPActionDefinition


def _validate_token(value: str, name: str) -> None:
    if not isinstance(value, str) or not _matches_identifier(value, 1):
        raise NipStackCoreUsageError(f"{name} must match ASCII [a-z][a-z0-9_]*.")


def _freeze_commands(value: Sequence[str], name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise NipStackCoreUsageError(f"{name} must be a sequence of nonempty single-line strings.")
    commands: list[str] = []
    for command in value:
        _validate_text(command, name)
        commands.append(command)
    return tuple(commands)


def _validate_http_path(value: str) -> None:
    if (
        not isinstance(value, str)
        or _PATH_CHARACTERS.fullmatch(value) is None
        or value.startswith("//")
    ):
        raise NipStackCoreUsageError("path must be an origin-relative ASCII URI path.")
    decoded: list[str] = []
    position = 0
    while position < len(value):
        character = value[position]
        if character == "%":
            pair = value[position + 1 : position + 3]
            if _HEX_PAIR.fullmatch(pair) is None:
                raise NipStackCoreUsageError("path contains an invalid percent escape.")
            byte = int(pair, 16)
            if byte <= 0x20 or byte == 0x7F or byte in (0x2F, 0x5C):
                raise NipStackCoreUsageError("path cannot contain encoded controls or separators.")
            character = chr(byte)
            position += 2
        decoded.append(character)
        position += 1
    if any(segment in (".", "..") for segment in "".join(decoded).split("/")):
        raise NipStackCoreUsageError("path cannot contain dot traversal segments.")


def _freeze_query(
    value: Sequence[tuple[str, str]] | None,
) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise NipStackCoreUsageError("query must be a sequence of string tuple pairs or None.")
    pairs: list[tuple[str, str]] = []
    for pair in value:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise NipStackCoreUsageError("query elements must be tuples of two strings.")
        for component in pair:
            if not isinstance(component, str) or any(
                unicodedata.category(character) in ("Cc", "Cs") for character in component
            ):
                raise NipStackCoreUsageError(
                    "query strings must have valid Unicode without controls."
                )
        if not pair[0]:
            raise NipStackCoreUsageError("query parameter names cannot be empty.")
        pairs.append((pair[0], pair[1]))
    return tuple(pairs)


def _freeze_headers(value: Mapping[str, str] | None) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise NipStackCoreUsageError("headers must be a string mapping or None.")
    copied: dict[str, str] = {}
    seen: set[str] = set()
    for name, content in value.items():
        if not isinstance(name, str) or _HEADER_NAME.fullmatch(name) is None:
            raise NipStackCoreUsageError("header names must follow HTTP token syntax.")
        normalized = name.lower()
        if normalized in seen:
            raise NipStackCoreUsageError("headers cannot repeat names ignoring case.")
        if normalized not in _TECHNICAL_HEADERS:
            raise NipStackCoreUsageError("header is not in the approved technical allowlist.")
        if not isinstance(content, str) or any(
            character != "\t" and not 0x20 <= ord(character) <= 0x7E for character in content
        ):
            raise NipStackCoreUsageError("header values must use ASCII field characters.")
        seen.add(normalized)
        copied[name] = content
    return MappingProxyType(copied)


def _freeze_body(value: JSONDocument | None) -> JSONDocument | None:
    if value is None:
        return None
    if not isinstance(value, (Mapping, list, tuple)):
        raise NipStackCoreUsageError("body must have a JSON object or array root.")
    frozen = _freeze_json_value(value)
    assert isinstance(frozen, (Mapping, tuple))
    return frozen
