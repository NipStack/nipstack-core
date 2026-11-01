"""Secret display, validation and explicitly limited reflection guarantees."""

import json
import traceback
from dataclasses import FrozenInstanceError, asdict
from inspect import Parameter, signature

import pytest

from nipstack_core import NipStackCoreUsageError, SecretValue


@pytest.mark.parametrize("value", ["synthetic", " ", "\tpassword\n", "pässword", "\0"])
def test_secret_preserves_nonempty_strings_exactly(value: str) -> None:
    secret = SecretValue(value)

    assert secret.reveal() == value
    assert repr(secret) == str(secret) == "SecretValue('**********')"


@pytest.mark.parametrize("value", ["", None, True, 1, 1.5, b"secret", [], {}, object()])
def test_secret_rejects_invalid_values_without_coercion(value: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="nonempty string"):
        SecretValue(value)


def test_secret_display_is_independent_of_content_and_length() -> None:
    sentinel = "SYNTHETIC_SECRET_SENTINEL"
    secret = SecretValue(sentinel)

    for display in (str(secret), repr(secret), repr([secret]), repr({"secret": secret})):
        assert sentinel not in display
        assert "**********" in display
    assert str(secret) == str(SecretValue("x"))
    assert str(secret) == str(SecretValue("x" * 1000))


def test_secret_is_frozen_slotted_and_uses_identity_equality_and_hash() -> None:
    secret = SecretValue("synthetic")
    other = SecretValue("synthetic")

    assert not hasattr(secret, "__dict__")
    assert secret == secret
    assert secret != other
    assert secret != "synthetic"
    assert hash(secret) == object.__hash__(secret)
    assert len({secret, other}) == 2
    with pytest.raises(FrozenInstanceError):
        secret._value = "changed"
    with pytest.raises(FrozenInstanceError):
        delattr(secret, "_value")


def test_secret_signature_and_calls_outside_it_raise_native_type_error() -> None:
    assert signature(SecretValue).parameters["value"].kind is Parameter.POSITIONAL_ONLY
    with pytest.raises(TypeError):
        SecretValue()
    with pytest.raises(TypeError):
        SecretValue(value="synthetic")
    with pytest.raises(TypeError):
        SecretValue("synthetic", "extra")


def test_invalid_object_is_not_formatted_or_logged(caplog: pytest.LogCaptureFixture) -> None:
    class Unformattable:
        def __str__(self) -> str:
            raise AssertionError("Input must not be formatted.")

        def __repr__(self) -> str:
            raise AssertionError("Input must not be represented.")

    with pytest.raises(NipStackCoreUsageError) as raised:
        SecretValue(Unformattable())

    rendered = "".join(traceback.format_exception(raised.value))
    assert "Unformattable" not in str(raised.value)
    assert "Input must not" not in rendered
    assert not caplog.records


def test_reflective_serialization_is_not_promised_secret_safe() -> None:
    secret = SecretValue("SYNTHETIC_REFLECTION_SENTINEL")

    assert asdict(secret)["_value"] == secret.reveal()
    with pytest.raises(TypeError):
        json.dumps(secret)
    assert not hasattr(secret, "to_dict")
