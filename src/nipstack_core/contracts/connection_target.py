"""Offline endpoint, runtime-option and credential-free descriptor contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from ipaddress import ip_address
from sys import float_info
from typing import Literal

from .authentication import (
    BearerTokenAuth,
    NoAuth,
    SSHKeyAuth,
    UsernamePasswordAuth,
    _validate_file_reference,
)
from .errors import NipStackCoreUsageError

_DNS_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
_NUMERIC_LABEL = re.compile(r"(?:[0-9]+|0[xX][0-9a-fA-F]+)")


@dataclass(frozen=True, slots=True, kw_only=True)
class SSHEndpoint:
    """A bare SSH endpoint and trust options, independent of Profile drivers.

    Host-key verification is requested by default, not performed here. An
    unspecified known-hosts file delegates trusted-source selection to a future
    Connector, which must fail safely if trust is unavailable.

    Raises:
        NipStackCoreUsageError: Endpoint values or trust options are invalid.
    """

    host: str
    port: int = 22
    verify_host_key: bool = True
    known_hosts_file: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _validate_host(self.host)
        _validate_port(self.port)
        _validate_bool(self.verify_host_key, "verify_host_key")
        if self.known_hosts_file is not None:
            _validate_file_reference(self.known_hosts_file, "known_hosts_file")
            if not self.verify_host_key:
                raise NipStackCoreUsageError(
                    "known_hosts_file cannot be supplied when host-key verification is disabled."
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class HTTPEndpoint:
    """An HTTP origin with HTTPS and certificate verification requested by default.

    CA file references are checked lexically, without filesystem access. On
    plaintext HTTP, the default TLS flag is neutral and provides no encryption.

    Raises:
        NipStackCoreUsageError: Endpoint values or TLS options are invalid.
    """

    host: str
    scheme: Literal["http", "https"] = "https"
    port: int | None = None
    verify_tls: bool = True
    ca_file: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _validate_host(self.host)
        if not isinstance(self.scheme, str) or self.scheme not in ("http", "https"):
            raise NipStackCoreUsageError("scheme must be exactly http or https.")
        if self.port is not None:
            _validate_port(self.port)
        _validate_bool(self.verify_tls, "verify_tls")
        if self.ca_file is not None:
            _validate_file_reference(self.ca_file, "ca_file")
            if not self.verify_tls:
                raise NipStackCoreUsageError(
                    "ca_file cannot be supplied when TLS verification is disabled."
                )
        if self.scheme == "http" and (not self.verify_tls or self.ca_file is not None):
            raise NipStackCoreUsageError("plaintext HTTP requires default neutral TLS options.")

    @property
    def effective_port(self) -> int:
        if self.port is not None:
            return self.port
        return 443 if self.scheme == "https" else 80


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetDescriptor:
    """Credential-free endpoint metadata, not an anonymous or verified target.

    Raises:
        NipStackCoreUsageError: Scheme, host or port values are invalid.
    """

    scheme: Literal["ssh", "http", "https"]
    host: str
    port: int

    def __post_init__(self) -> None:
        if not isinstance(self.scheme, str) or self.scheme not in ("ssh", "http", "https"):
            raise NipStackCoreUsageError("scheme must be exactly ssh, http or https.")
        _validate_host(self.host)
        _validate_port(self.port)

    def to_dict(self) -> dict[str, str | int]:
        """Return only scheme, host and effective port for public serialization."""
        return {"scheme": self.scheme, "host": self.host, "port": self.port}


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ConnectionTarget:
    """One endpoint, explicit runtime authentication and optional timeout overrides.

    Equality and hashing are by identity. Authentication is excluded from the
    representation; reflective serialization is not secret-safe.

    Args:
        endpoint: Consumer-owned SSH endpoint or HTTP origin.
        authentication: Explicit credentials or NoAuth; never inferred from the environment.
        connect_timeout: Positive finite seconds, or None for no Target override.
        operation_timeout: Positive finite seconds, or None for no Target override.

    Raises:
        NipStackCoreUsageError: Types, auth compatibility or timeout values are invalid.
    """

    endpoint: SSHEndpoint | HTTPEndpoint
    authentication: UsernamePasswordAuth | SSHKeyAuth | BearerTokenAuth | NoAuth = field(repr=False)
    connect_timeout: float | None = None
    operation_timeout: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, (SSHEndpoint, HTTPEndpoint)):
            raise NipStackCoreUsageError("endpoint must be an SSHEndpoint or HTTPEndpoint.")
        if not isinstance(
            self.authentication, (UsernamePasswordAuth, SSHKeyAuth, BearerTokenAuth, NoAuth)
        ):
            raise NipStackCoreUsageError("authentication must be an approved authentication type.")
        if isinstance(self.endpoint, SSHEndpoint):
            if not isinstance(self.authentication, (UsernamePasswordAuth, SSHKeyAuth)):
                raise NipStackCoreUsageError(
                    "SSH requires username/password or SSH key authentication."
                )
        elif self.endpoint.scheme == "http":
            if not isinstance(self.authentication, NoAuth):
                raise NipStackCoreUsageError("plaintext HTTP accepts only NoAuth.")
        elif isinstance(self.authentication, SSHKeyAuth):
            raise NipStackCoreUsageError("HTTPS does not accept SSH key authentication.")

        object.__setattr__(
            self, "connect_timeout", _validate_timeout(self.connect_timeout, "connect_timeout")
        )
        object.__setattr__(
            self,
            "operation_timeout",
            _validate_timeout(self.operation_timeout, "operation_timeout"),
        )

    def to_descriptor(self) -> TargetDescriptor:
        """Project only endpoint metadata, without retaining auth or option references."""
        if isinstance(self.endpoint, SSHEndpoint):
            return TargetDescriptor(scheme="ssh", host=self.endpoint.host, port=self.endpoint.port)
        return TargetDescriptor(
            scheme=self.endpoint.scheme,
            host=self.endpoint.host,
            port=self.endpoint.effective_port,
        )


def _is_ip_address(host: str) -> bool:
    try:
        ip_address(host)
    except ValueError:
        return False
    return True


def _validate_host(host: str) -> None:
    if not isinstance(host, str) or not host or len(host) > 254 or not host.isascii():
        raise NipStackCoreUsageError("host must be a bare IP address or ASCII DNS name.")
    if "%" not in host and _is_ip_address(host):
        return

    dns_name = host[:-1] if host.endswith(".") else host
    labels = dns_name.split(".")
    if (
        len(dns_name) > 253
        or any(_DNS_LABEL.fullmatch(label) is None for label in labels)
        or all(_NUMERIC_LABEL.fullmatch(label) is not None for label in labels)
    ):
        raise NipStackCoreUsageError(
            "host must be a bare IP address or ASCII DNS name, without URL components "
            "or an IPv6 zone identifier."
        )


def _validate_port(port: int) -> None:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise NipStackCoreUsageError("port must be an integer from 1 to 65535.")


def _validate_bool(value: bool, name: str) -> None:
    if not isinstance(value, bool):
        raise NipStackCoreUsageError(f"{name} must be a bool.")


def _validate_timeout(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 < value <= float_info.max
    ):
        raise NipStackCoreUsageError(
            f"{name} must be positive finite seconds representable as a float, or None."
        )
    return float(value)
