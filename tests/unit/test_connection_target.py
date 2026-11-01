"""Offline endpoints, auth compatibility, runtime options and public descriptors."""

import builtins
import io
import json
import os
import socket
import traceback
from collections.abc import Callable
from dataclasses import FrozenInstanceError, asdict, fields
from decimal import Decimal
from inspect import Parameter, signature
from pathlib import Path
from sys import float_info
from typing import NoReturn

import pytest

from nipstack_core import (
    BearerTokenAuth,
    ConnectionTarget,
    HTTPEndpoint,
    NipStackCoreUsageError,
    NoAuth,
    SecretValue,
    SSHEndpoint,
    SSHKeyAuth,
    TargetDescriptor,
    UsernamePasswordAuth,
)


@pytest.mark.parametrize("kind", [SSHEndpoint, HTTPEndpoint])
@pytest.mark.parametrize(
    "host",
    [
        "192.0.2.1",
        "2001:db8::1",
        "::1",
        "::",
        "2001:DB8::A",
        "::ffff:192.0.2.1",
        "localhost",
        "device-1",
        "DEVICE.example.invalid",
        "a.example.invalid.",
        "xn--bcher-kva.example",
        "a" * 63,
        ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61]),
    ],
)
def test_valid_hosts_are_preserved_without_normalization(
    kind: Callable[..., object], host: str
) -> None:
    endpoint = kind(host=host)

    assert endpoint.host == host


@pytest.mark.parametrize("kind", [SSHEndpoint, HTTPEndpoint])
@pytest.mark.parametrize(
    "host",
    [
        "",
        " ",
        "host ",
        " host",
        "ho\nst",
        "host\n",
        "https://example.invalid",
        "ssh://example.invalid",
        "user@example.invalid",
        "host/path",
        "host\\path",
        "host?query",
        "host#fragment",
        "[2001:db8::1]",
        "host:443",
        "fe80::1%eth0",
        "fe80::1%25eth0",
        "ä.example",
        "a..b",
        "-host",
        "host-",
        "a_b",
        ".host",
        "host..",
        "256.1.1.1",
        "127.1",
        "2130706433",
        "0177.0.0.1",
        "0x7f000001",
        "0x7f.0.0.1",
        "a" * 64,
        ".".join(["a" * 63] * 4),
        None,
        True,
        1,
        [],
        object(),
    ],
)
def test_invalid_hosts_do_not_become_urls_or_dns_fallbacks(
    kind: Callable[..., object], host: object
) -> None:
    with pytest.raises(NipStackCoreUsageError, match="host"):
        kind(host=host)


def test_dns_name_length_excludes_one_optional_final_dot() -> None:
    name = ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61])

    assert len(name) == 253
    assert HTTPEndpoint(host=name + ".").host == name + "."
    with pytest.raises(NipStackCoreUsageError):
        HTTPEndpoint(host=name + "e.")


@pytest.mark.parametrize("kind", [SSHEndpoint, HTTPEndpoint])
@pytest.mark.parametrize("port", [1, 22, 80, 443, 65535])
def test_port_bounds_are_inclusive(kind: Callable[..., object], port: int) -> None:
    assert kind(host="example.invalid", port=port).port == port


@pytest.mark.parametrize("kind", [SSHEndpoint, HTTPEndpoint])
@pytest.mark.parametrize("port", [True, False, 0, -1, 65536, 1.5, "22", [], object()])
def test_invalid_ports_are_rejected(kind: Callable[..., object], port: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="port"):
        kind(host="example.invalid", port=port)


def test_default_ports_and_http_effective_port_are_explicit() -> None:
    assert SSHEndpoint(host="example.invalid").port == 22
    https = HTTPEndpoint(host="example.invalid")
    http = HTTPEndpoint(host="example.invalid", scheme="http")
    assert https.port is http.port is None
    assert https.effective_port == 443
    assert http.effective_port == 80
    assert HTTPEndpoint(host="example.invalid", port=8443).effective_port == 8443
    with pytest.raises(NipStackCoreUsageError):
        SSHEndpoint(host="example.invalid", port=None)


@pytest.mark.parametrize("scheme", ["HTTP", "HTTPS", "ssh", "", "https://", None, True, 1, []])
def test_http_scheme_is_strict(scheme: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="scheme"):
        HTTPEndpoint(host="example.invalid", scheme=scheme)


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], object()])
def test_verification_flags_require_actual_bools(value: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="verify_tls"):
        HTTPEndpoint(host="example.invalid", verify_tls=value)
    with pytest.raises(NipStackCoreUsageError, match="verify_host_key"):
        SSHEndpoint(host="example.invalid", verify_host_key=value)


def test_verification_defaults_opt_outs_and_explicit_trust_files() -> None:
    assert HTTPEndpoint(host="example.invalid").verify_tls is True
    assert SSHEndpoint(host="example.invalid").verify_host_key is True
    assert HTTPEndpoint(host="example.invalid", verify_tls=False).verify_tls is False
    assert SSHEndpoint(host="example.invalid", verify_host_key=False).verify_host_key is False
    tls = HTTPEndpoint(host="example.invalid", ca_file="/synthetic/$CA_FILE")
    ssh = SSHEndpoint(host="example.invalid", known_hosts_file="/synthetic/../known-hosts")
    assert tls.ca_file == "/synthetic/$CA_FILE"
    assert ssh.known_hosts_file == "/synthetic/../known-hosts"
    assert "/synthetic" not in repr(tls)
    assert "/synthetic" not in repr(ssh)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "relative/file",
        "~/file",
        " /synthetic/file",
        "/synthetic/file ",
        "/synthetic/\0file",
        "/synthetic/\nfile",
        "/synthetic/\x85file",
        True,
        1,
        [],
        object(),
    ],
)
def test_trust_file_validation_is_lexical(path: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="ca_file"):
        HTTPEndpoint(host="example.invalid", ca_file=path)
    with pytest.raises(NipStackCoreUsageError, match="known_hosts_file"):
        SSHEndpoint(host="example.invalid", known_hosts_file=path)


def test_conflicting_or_inapplicable_trust_options_are_rejected() -> None:
    with pytest.raises(NipStackCoreUsageError, match="ca_file"):
        HTTPEndpoint(host="example.invalid", verify_tls=False, ca_file="/synthetic/ca")
    with pytest.raises(NipStackCoreUsageError, match="known_hosts_file"):
        SSHEndpoint(
            host="example.invalid", verify_host_key=False, known_hosts_file="/synthetic/hosts"
        )
    with pytest.raises(NipStackCoreUsageError, match="plaintext HTTP"):
        HTTPEndpoint(host="example.invalid", scheme="http", verify_tls=False)
    with pytest.raises(NipStackCoreUsageError, match="plaintext HTTP"):
        HTTPEndpoint(host="example.invalid", scheme="http", ca_file="/synthetic/ca")


@pytest.mark.parametrize("scheme", ["ssh", "https", "http"])
@pytest.mark.parametrize("auth_kind", ["password", "key", "bearer", "none"])
def test_complete_auth_transport_matrix(scheme: str, auth_kind: str) -> None:
    auths = {
        "password": UsernamePasswordAuth(username="user:name", password=SecretValue("synthetic")),
        "key": SSHKeyAuth(username="user", key_file="/synthetic/key"),
        "bearer": BearerTokenAuth(token=SecretValue("synthetic")),
        "none": NoAuth(),
    }
    endpoint = (
        SSHEndpoint(host="example.invalid")
        if scheme == "ssh"
        else HTTPEndpoint(host="example.invalid", scheme=scheme)
    )
    accepted = {
        "ssh": {"password", "key"},
        "https": {"password", "bearer", "none"},
        "http": {"none"},
    }
    if auth_kind in accepted[scheme]:
        target = ConnectionTarget(endpoint=endpoint, authentication=auths[auth_kind])
        assert target.endpoint is endpoint
        assert target.authentication is auths[auth_kind]
    else:
        with pytest.raises(NipStackCoreUsageError):
            ConnectionTarget(endpoint=endpoint, authentication=auths[auth_kind])


@pytest.mark.parametrize("value", [None, "https://example.invalid", {}, [], True, object()])
def test_target_rejects_non_endpoint_objects(value: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="endpoint"):
        ConnectionTarget(endpoint=value, authentication=NoAuth())


@pytest.mark.parametrize("value", [None, "password", {}, [], True, SecretValue("synthetic")])
def test_target_rejects_untyped_authentication(value: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="authentication"):
        ConnectionTarget(endpoint=HTTPEndpoint(host="example.invalid"), authentication=value)


@pytest.mark.parametrize("name", ["connect_timeout", "operation_timeout"])
@pytest.mark.parametrize(
    "value", [None, 1, 5, 0.25, float_info.max, float.fromhex("0x0.0000000000001p-1022")]
)
def test_optional_timeouts_preserve_absence_and_normalize_numbers(
    name: str, value: float | None
) -> None:
    target = ConnectionTarget(
        endpoint=HTTPEndpoint(host="example.invalid"),
        authentication=NoAuth(),
        **{name: value},
    )
    actual = getattr(target, name)
    if value is None:
        assert actual is None
    else:
        assert actual == value
        assert type(actual) is float


@pytest.mark.parametrize("name", ["connect_timeout", "operation_timeout"])
@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        0,
        -1,
        -0.1,
        float("nan"),
        float("inf"),
        -float("inf"),
        "5",
        Decimal("5"),
        [],
        object(),
        pytest.param(10**10000, id="oversized-integer"),
    ],
)
def test_invalid_timeouts_raise_usage_errors_without_overflow(name: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match=name):
        ConnectionTarget(
            endpoint=HTTPEndpoint(host="example.invalid"),
            authentication=NoAuth(),
            **{name: value},
        )


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        (SSHEndpoint(host="2001:db8::1"), {"scheme": "ssh", "host": "2001:db8::1", "port": 22}),
        (
            HTTPEndpoint(host="example.invalid"),
            {"scheme": "https", "host": "example.invalid", "port": 443},
        ),
        (
            HTTPEndpoint(host="example.invalid", scheme="http"),
            {"scheme": "http", "host": "example.invalid", "port": 80},
        ),
        (
            HTTPEndpoint(host="example.invalid", port=8443),
            {"scheme": "https", "host": "example.invalid", "port": 8443},
        ),
    ],
)
def test_descriptor_contains_exactly_effective_endpoint_metadata(
    endpoint: SSHEndpoint | HTTPEndpoint, expected: dict[str, str | int]
) -> None:
    auth = (
        SSHKeyAuth(username="user", key_file="/synthetic/key")
        if isinstance(endpoint, SSHEndpoint)
        else NoAuth()
    )
    target = ConnectionTarget(endpoint=endpoint, authentication=auth)
    descriptor = target.to_descriptor()

    assert {field.name for field in fields(descriptor)} == {"scheme", "host", "port"}
    assert descriptor.to_dict() == asdict(descriptor) == expected
    assert json.loads(json.dumps(descriptor.to_dict())) == expected
    copied = descriptor.to_dict()
    copied["host"] = "changed"
    assert descriptor.to_dict() == expected
    assert not hasattr(descriptor, "__dict__")
    assert not hasattr(descriptor, "authentication")
    assert not hasattr(target, "to_dict")
    assert not hasattr(descriptor, "endpoint")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scheme": "ftp", "host": "example.invalid", "port": 22},
        {"scheme": "https", "host": "user@example.invalid", "port": 443},
        {"scheme": "ssh", "host": "example.invalid", "port": True},
        {"scheme": "http", "host": "example.invalid", "port": None},
    ],
)
def test_descriptor_direct_construction_is_validated(kwargs: dict[str, object]) -> None:
    with pytest.raises(NipStackCoreUsageError):
        TargetDescriptor(**kwargs)


def test_secrets_and_secret_bearing_options_are_absent_from_target_output() -> None:
    secret = SecretValue("SYNTHETIC_SECRET_SENTINEL")
    endpoints_and_auth = [
        (
            SSHEndpoint(host="example.invalid", known_hosts_file="/SYNTHETIC_TRUST_PATH"),
            SSHKeyAuth(
                username="SYNTHETIC_USERNAME", key_file="/SYNTHETIC_KEY_PATH", passphrase=secret
            ),
        ),
        (
            HTTPEndpoint(host="example.invalid", ca_file="/SYNTHETIC_CA_PATH"),
            BearerTokenAuth(token=secret),
        ),
        (
            HTTPEndpoint(host="example.invalid"),
            UsernamePasswordAuth(username="SYNTHETIC_USERNAME", password=secret),
        ),
    ]
    for endpoint, auth in endpoints_and_auth:
        target = ConnectionTarget(endpoint=endpoint, authentication=auth)
        descriptor = target.to_descriptor()
        for display in (
            repr(target),
            str(target),
            repr(descriptor),
            str(descriptor),
            json.dumps(descriptor.to_dict()),
        ):
            assert "SYNTHETIC" not in display


def test_invalid_host_tracebacks_do_not_expose_parser_inputs() -> None:
    invalid = "SYNTHETIC_HOST_SENTINEL@host"
    with pytest.raises(NipStackCoreUsageError) as raised:
        HTTPEndpoint(host=invalid)

    assert "SYNTHETIC_HOST_SENTINEL" not in "".join(traceback.format_exception(raised.value))
    assert raised.value.__context__ is None


@pytest.mark.parametrize(
    "value",
    [
        SSHEndpoint(host="example.invalid"),
        HTTPEndpoint(host="example.invalid"),
        TargetDescriptor(scheme="ssh", host="example.invalid", port=22),
        ConnectionTarget(endpoint=HTTPEndpoint(host="example.invalid"), authentication=NoAuth()),
    ],
)
def test_target_and_endpoint_contracts_are_frozen_and_slotted(value: object) -> None:
    assert not hasattr(value, "__dict__")
    for attribute in fields(value):
        with pytest.raises(FrozenInstanceError):
            setattr(value, attribute.name, None)
        with pytest.raises(FrozenInstanceError):
            delattr(value, attribute.name)


def test_endpoint_descriptor_value_equality_and_target_identity() -> None:
    endpoint = HTTPEndpoint(host="example.invalid")
    assert endpoint == HTTPEndpoint(host="example.invalid")
    assert hash(endpoint) == hash(HTTPEndpoint(host="example.invalid"))
    assert endpoint != HTTPEndpoint(host="EXAMPLE.invalid")
    assert SSHEndpoint(host="example.invalid") == SSHEndpoint(host="example.invalid")
    first = ConnectionTarget(endpoint=endpoint, authentication=NoAuth())
    second = ConnectionTarget(endpoint=endpoint, authentication=NoAuth())
    assert first != second
    assert hash(first) == object.__hash__(first)
    assert first.to_descriptor() == second.to_descriptor()
    assert hash(first.to_descriptor()) == hash(second.to_descriptor())


@pytest.mark.parametrize("kind", [SSHEndpoint, HTTPEndpoint, ConnectionTarget, TargetDescriptor])
def test_target_contract_signatures_are_keyword_only(kind: Callable[..., object]) -> None:
    assert all(
        parameter.kind is Parameter.KEYWORD_ONLY
        for parameter in signature(kind).parameters.values()
    )
    with pytest.raises(TypeError):
        kind()
    with pytest.raises(TypeError):
        kind("example.invalid")
    with pytest.raises(TypeError):
        kind(unexpected="synthetic")
    with pytest.raises(TypeError):
        TargetDescriptor(scheme="https", host="example.invalid", port=443, authentication=NoAuth())
    with pytest.raises(TypeError):
        ConnectionTarget(
            endpoint=HTTPEndpoint(host="example.invalid"),
            authentication=NoAuth(),
            allow_plaintext_auth=True,
        )


def test_all_constructors_and_projection_remain_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_io(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("Contract construction must not perform I/O.")

    with monkeypatch.context() as guarded:
        for owner, name in [
            (builtins, "open"),
            (io, "open"),
            (os, "stat"),
            (Path, "open"),
            (Path, "read_text"),
            (Path, "read_bytes"),
            (Path, "stat"),
            (Path, "resolve"),
            (Path, "expanduser"),
            (socket, "socket"),
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (socket, "gethostbyname"),
        ]:
            guarded.setattr(owner, name, unexpected_io)
        secret = SecretValue("synthetic")
        password = UsernamePasswordAuth(username="user:name", password=secret)
        key = SSHKeyAuth(username="user", key_file="/synthetic/key", passphrase=secret)
        bearer = BearerTokenAuth(token=secret)
        no_auth = NoAuth()
        ssh = SSHEndpoint(host="example.invalid", known_hosts_file="/synthetic/known-hosts")
        https = HTTPEndpoint(host="example.invalid", ca_file="/synthetic/ca")
        for endpoint, auth in [(ssh, password), (ssh, key), (https, bearer), (https, no_auth)]:
            target = ConnectionTarget(
                endpoint=endpoint, authentication=auth, connect_timeout=1, operation_timeout=2
            )
            assert target.to_descriptor().to_dict()["host"] == "example.invalid"
        TargetDescriptor(scheme="http", host="192.0.2.1", port=80)
