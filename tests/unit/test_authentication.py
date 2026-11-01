"""Offline typed authentication, redaction and boundary-validation tests."""

import traceback
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields
from inspect import Parameter, signature

import pytest

from nipstack_core import (
    BearerTokenAuth,
    NipStackCoreUsageError,
    NoAuth,
    SecretValue,
    SSHKeyAuth,
    UsernamePasswordAuth,
)


@pytest.mark.parametrize("username", ["sample-user", "user:name", "user name", "utilisateur-é"])
def test_usernames_are_preserved_in_both_auth_forms(username: str) -> None:
    secret = SecretValue(" \tsynthetic-password\n")
    password_auth = UsernamePasswordAuth(username=username, password=secret)
    key_auth = SSHKeyAuth(
        username=username, key_file="/synthetic/../private-key", passphrase=secret
    )

    assert password_auth.username == key_auth.username == username
    assert password_auth.password is key_auth.passphrase is secret
    assert secret.reveal() == " \tsynthetic-password\n"
    assert key_auth.key_file == "/synthetic/../private-key"


@pytest.mark.parametrize(
    "username",
    [
        "",
        " user",
        "user ",
        "user\nname",
        "user\0name",
        "user\x7fname",
        "user\x85name",
        None,
        True,
        1,
    ],
)
@pytest.mark.parametrize("kind", ["password", "key"])
def test_invalid_usernames_raise_usage_errors(username: object, kind: str) -> None:
    with pytest.raises(NipStackCoreUsageError, match="username"):
        if kind == "password":
            UsernamePasswordAuth(username=username, password=SecretValue("synthetic"))
        else:
            SSHKeyAuth(username=username, key_file="/synthetic/key")


@pytest.mark.parametrize("value", [None, "raw-secret", b"secret", True, 1, [], object()])
def test_password_and_token_require_explicit_secret_values(value: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="password"):
        UsernamePasswordAuth(username="user", password=value)
    with pytest.raises(NipStackCoreUsageError, match="token"):
        BearerTokenAuth(token=value)


@pytest.mark.parametrize("value", ["raw-secret", True, 1, b"secret", [], object()])
def test_key_passphrase_rejects_non_secret_values(value: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="passphrase"):
        SSHKeyAuth(username="user", key_file="/synthetic/key", passphrase=value)


def test_key_passphrase_can_be_explicitly_absent() -> None:
    auth = SSHKeyAuth(username="user", key_file="/synthetic/key")

    assert auth.passphrase is None


@pytest.mark.parametrize(
    "path",
    [
        "",
        "relative/key",
        "~/key",
        " /synthetic/key",
        "/synthetic/key ",
        "/synthetic/\0key",
        "/synthetic/\nkey",
        "/synthetic/\x85key",
        None,
        True,
        1,
        [],
        SecretValue("synthetic"),
    ],
)
def test_key_file_rejects_invalid_references_without_io(path: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="key_file"):
        SSHKeyAuth(username="user", key_file=path)


def test_file_reference_does_not_expand_environment_variables() -> None:
    path = "/synthetic/$KEY_FILE"

    assert SSHKeyAuth(username="user", key_file=path).key_file == path


@pytest.mark.parametrize("token", ["a", "abc123", "-._~+/", "abc=", "abc==", "a/b+c_~.-=="])
def test_bearer_accepts_rfc6750_b64token_syntax(token: str) -> None:
    secret = SecretValue(token)

    assert BearerTokenAuth(token=secret).token is secret


@pytest.mark.parametrize(
    "token",
    [" ", " a", "a ", "a\tb", "a\nb", "a\rb", "a\n", "a:b", "a,b", "a=b", "=", "ä", "a\0b"],
)
def test_bearer_rejects_whitespace_controls_and_invalid_syntax(token: str) -> None:
    with pytest.raises(NipStackCoreUsageError, match="RFC 6750"):
        BearerTokenAuth(token=SecretValue(token))


def test_auth_representations_hide_all_credential_fields() -> None:
    username = "SYNTHETIC_USERNAME_SENTINEL"
    password = SecretValue("SYNTHETIC_PASSWORD_SENTINEL")
    key_file = "/SYNTHETIC_KEY_PATH_SENTINEL"
    passphrase = SecretValue("SYNTHETIC_PASSPHRASE_SENTINEL")
    token = SecretValue("SYNTHETIC_TOKEN_SENTINEL")
    auths = [
        UsernamePasswordAuth(username=username, password=password),
        SSHKeyAuth(username=username, key_file=key_file, passphrase=passphrase),
        BearerTokenAuth(token=token),
        NoAuth(),
    ]

    for auth in auths:
        assert repr(auth) == str(auth) == f"{type(auth).__name__}()"
        assert "SYNTHETIC" not in repr([auth])
        assert not hasattr(auth, "to_dict")


@pytest.mark.parametrize(
    "auth",
    [
        UsernamePasswordAuth(username="user", password=SecretValue("synthetic")),
        SSHKeyAuth(username="user", key_file="/synthetic/key"),
        BearerTokenAuth(token=SecretValue("synthetic")),
    ],
)
def test_credential_objects_are_frozen_slotted_and_identity_values(auth: object) -> None:
    assert not hasattr(auth, "__dict__")
    assert hash(auth) == object.__hash__(auth)
    for attribute in fields(auth):
        with pytest.raises(FrozenInstanceError):
            setattr(auth, attribute.name, None)
        with pytest.raises(FrozenInstanceError):
            delattr(auth, attribute.name)


def test_auth_equality_does_not_compare_secret_contents() -> None:
    secret = SecretValue("synthetic")
    first = UsernamePasswordAuth(username="user", password=secret)
    second = UsernamePasswordAuth(username="user", password=secret)

    assert first != second
    assert len({first, second}) == 2
    assert SSHKeyAuth(username="user", key_file="/synthetic/key") != SSHKeyAuth(
        username="user", key_file="/synthetic/key"
    )
    assert BearerTokenAuth(token=secret) != BearerTokenAuth(token=secret)
    assert NoAuth() == NoAuth()
    assert hash(NoAuth()) == hash(NoAuth())
    assert not fields(NoAuth())
    assert not hasattr(NoAuth(), "__dict__")


@pytest.mark.parametrize("kind", [UsernamePasswordAuth, SSHKeyAuth, BearerTokenAuth])
def test_auth_constructors_are_keyword_only(kind: Callable[..., object]) -> None:
    assert all(
        parameter.kind is Parameter.KEYWORD_ONLY
        for parameter in signature(kind).parameters.values()
    )
    with pytest.raises(TypeError):
        kind()
    with pytest.raises(TypeError):
        kind("unexpected")
    with pytest.raises(TypeError):
        kind(unexpected="synthetic")
    with pytest.raises(TypeError):
        NoAuth(username="user")


def test_invalid_secret_syntax_is_not_echoed_in_exceptions() -> None:
    invalid = "SYNTHETIC_TOKEN_SENTINEL\r\n"
    with pytest.raises(NipStackCoreUsageError) as raised:
        BearerTokenAuth(token=SecretValue(invalid))

    assert "SYNTHETIC_TOKEN_SENTINEL" not in str(raised.value)
    assert "SYNTHETIC_TOKEN_SENTINEL" not in "".join(traceback.format_exception(raised.value))


def test_invalid_inputs_are_not_formatted() -> None:
    class Unformattable:
        def __str__(self) -> str:
            raise AssertionError("Input must not be formatted.")

        def __repr__(self) -> str:
            raise AssertionError("Input must not be represented.")

    invalid = Unformattable()
    calls = [
        lambda: UsernamePasswordAuth(username=invalid, password=SecretValue("synthetic")),
        lambda: UsernamePasswordAuth(username="user", password=invalid),
        lambda: SSHKeyAuth(username="user", key_file=invalid),
        lambda: SSHKeyAuth(username="user", key_file="/synthetic/key", passphrase=invalid),
        lambda: BearerTokenAuth(token=invalid),
    ]
    for call in calls:
        with pytest.raises(NipStackCoreUsageError):
            call()
