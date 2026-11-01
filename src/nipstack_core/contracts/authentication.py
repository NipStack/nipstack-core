"""Typed runtime authentication data, without transport or auth-strategy logic."""

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePath

from .errors import NipStackCoreUsageError
from .secrets import SecretValue

_BEARER_TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*")


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class UsernamePasswordAuth:
    """Username/password data for SSH or HTTPS, with identity equality.

    Colons in usernames are accepted. HTTP Basic-specific restrictions belong
    to a future AuthStrategy. Neither field appears in the representation.

    Raises:
        NipStackCoreUsageError: The username or secret type is invalid.
    """

    username: str = field(repr=False)
    password: SecretValue = field(repr=False)

    def __post_init__(self) -> None:
        _validate_username(self.username)
        if not isinstance(self.password, SecretValue):
            raise NipStackCoreUsageError("password must be a SecretValue.")


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class SSHKeyAuth:
    """SSH key-file data; file existence, content and permissions are not checked.

    The absolute local path is preserved verbatim. All fields are hidden from
    the representation, and equality is by identity.

    Raises:
        NipStackCoreUsageError: A username, file reference or passphrase is invalid.
    """

    username: str = field(repr=False)
    key_file: str = field(repr=False)
    passphrase: SecretValue | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _validate_username(self.username)
        _validate_file_reference(self.key_file, "key_file")
        if self.passphrase is not None and not isinstance(self.passphrase, SecretValue):
            raise NipStackCoreUsageError("passphrase must be a SecretValue or None.")


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class BearerTokenAuth:
    """An RFC 6750 ASCII b64token value for HTTPS, with identity equality.

    Raises:
        NipStackCoreUsageError: The token is not a SecretValue or has invalid syntax.
    """

    token: SecretValue = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.token, SecretValue):
            raise NipStackCoreUsageError("token must be a SecretValue.")
        if _BEARER_TOKEN.fullmatch(self.token.reveal()) is None:
            raise NipStackCoreUsageError("token must match the RFC 6750 ASCII b64token syntax.")


@dataclass(frozen=True, slots=True)
class NoAuth:
    """Explicitly request no authentication for HTTP or HTTPS."""


def _has_control_characters(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _validate_username(username: str) -> None:
    if (
        not isinstance(username, str)
        or not username
        or username != username.strip()
        or _has_control_characters(username)
    ):
        raise NipStackCoreUsageError(
            "username must be a nonempty string without peripheral whitespace "
            "or control characters."
        )


def _validate_file_reference(value: str, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or _has_control_characters(value)
        or not PurePath(value).is_absolute()
    ):
        raise NipStackCoreUsageError(
            f"{name} must be an absolute local-path string without peripheral "
            "whitespace or control characters."
        )
