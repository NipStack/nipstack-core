"""Explicit request selection, credential boundaries and untouched caller controls."""

import builtins
import io
import socket
import time
import uuid
from dataclasses import FrozenInstanceError, fields, replace
from inspect import Parameter, signature
from pathlib import Path

import pytest

from nipstack_core import (
    CollectionRequest,
    ConnectionTarget,
    ExecutionEvent,
    FeatureSelection,
    FeatureSelectionKind,
    HTTPEndpoint,
    NipStackCoreUsageError,
    NoAuth,
    ProfileIdentity,
    RawArtifactPolicy,
    SecretValue,
    SSHEndpoint,
    SSHKeyAuth,
    UsernamePasswordAuth,
)


def request() -> CollectionRequest:
    return CollectionRequest(
        profile_id="example.synthetic",
        target=ConnectionTarget(
            endpoint=HTTPEndpoint(host="example.invalid"), authentication=NoAuth()
        ),
        selection=FeatureSelection.features("check.system.status"),
    )


@pytest.mark.parametrize(
    "selection",
    [
        FeatureSelection.all(),
        FeatureSelection.modes("config", "check"),
        FeatureSelection.features("check.system.status"),
    ],
)
def test_every_explicit_selection_is_accepted_and_preserved(selection: FeatureSelection) -> None:
    value = replace(request(), selection=selection)
    assert value.selection is selection
    assert (selection.kind is FeatureSelectionKind.ALL) is (selection.values == ())
    assert value.raw_artifact_policy is RawArtifactPolicy.NONE
    assert value.correlation_id is None
    assert value.execution_control is None


def test_selection_is_mandatory_with_no_all_fallback() -> None:
    with pytest.raises(TypeError, match="selection"):
        CollectionRequest(profile_id="example.synthetic", target=request().target)


@pytest.mark.parametrize(
    "field,value",
    [
        ("target", None),
        ("target", request().target.to_descriptor()),
        ("target", HTTPEndpoint(host="example.invalid")),
        ("target", "example.invalid"),
        ("selection", None),
        ("selection", "all"),
        ("selection", []),
        ("selection", FeatureSelectionKind.ALL),
        ("raw_artifact_policy", "NONE"),
        ("raw_artifact_policy", None),
        ("raw_artifact_policy", True),
    ],
)
def test_request_rejects_invalid_boundary_types(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(request(), **{field: value})


@pytest.mark.parametrize("field", ["profile_id", "correlation_id"])
@pytest.mark.parametrize("value", [1, True, "", " leading", "trailing ", "a\nb", "\0", "\ud800"])
def test_request_ids_follow_20c_text_rules(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(request(), **{field: value})


def test_profile_id_is_opaque_not_a_feature_id_or_registry_lookup() -> None:
    identifier = "vendor/model @ local"
    value = replace(request(), profile_id=identifier, correlation_id="opaque correlation")
    assert value.profile_id == ProfileIdentity(profile_id=identifier).profile_id
    assert value.correlation_id == "opaque correlation"
    for policy in RawArtifactPolicy:
        assert replace(value, raw_artifact_policy=policy).raw_artifact_policy is policy


class UntouchedControl:
    def __getattribute__(self, name: str) -> object:
        raise AssertionError("Request construction must not inspect the control.")

    def __repr__(self) -> str:
        raise AssertionError("The control must not be displayed.")

    def __eq__(self, other: object) -> bool:
        raise AssertionError("The control must not be compared.")

    def __hash__(self) -> int:
        raise AssertionError("The control must not be hashed.")


def test_control_is_not_inspected_invoked_displayed_compared_or_hashed() -> None:
    control = UntouchedControl()
    value = replace(request(), execution_control=control)
    assert value.execution_control is control
    assert value == value
    assert value != replace(value)
    assert hash(value) == object.__hash__(value)
    assert "UntouchedControl" not in str(value) + repr(value)


def test_caller_control_can_remain_mutable_without_runtime_calls() -> None:
    class Control:
        cancelled = False

        def should_cancel(self) -> bool:
            raise AssertionError("Cancellation must not be polled.")

        def on_event(self, event: ExecutionEvent) -> None:
            raise AssertionError("Events must not be emitted.")

    control = Control()
    value = replace(request(), execution_control=control)
    control.cancelled = True
    assert value.execution_control is control
    assert control.cancelled


def test_request_repr_never_traverses_target_credentials_or_opaque_ids() -> None:
    sentinel = "SYNTHETIC_CREDENTIAL_SENTINEL"
    secret = SecretValue(sentinel)
    for auth in (
        UsernamePasswordAuth(username=sentinel, password=secret),
        SSHKeyAuth(username=sentinel, key_file="/SYNTHETIC_KEY_PATH", passphrase=secret),
    ):
        target = ConnectionTarget(
            endpoint=SSHEndpoint(
                host="private.example.invalid", known_hosts_file="/SYNTHETIC_TRUST_PATH"
            ),
            authentication=auth,
        )
        value = replace(
            request(),
            target=target,
            profile_id=sentinel,
            correlation_id=sentinel,
            execution_control=UntouchedControl(),
        )
        for display in (str(value), repr(value), repr([value]), repr({"request": value})):
            assert "SYNTHETIC" not in display
            assert "private.example.invalid" not in display
        assert not hasattr(value, "to_dict")
        assert not hasattr(value, "to_json")


def test_invalid_objects_are_not_formatted_or_logged(caplog: pytest.LogCaptureFixture) -> None:
    class Unformattable:
        def __str__(self) -> str:
            raise AssertionError("Do not format invalid inputs.")

        def __repr__(self) -> str:
            raise AssertionError("Do not represent invalid inputs.")

    for name in ("profile_id", "target", "selection", "raw_artifact_policy", "correlation_id"):
        with pytest.raises(NipStackCoreUsageError):
            replace(request(), **{name: Unformattable()})
    assert not caplog.records


def test_request_is_frozen_slotted_keyword_only_and_has_identity_equality() -> None:
    value = request()
    assert not hasattr(value, "__dict__")
    assert value != replace(value)
    assert hash(value) == object.__hash__(value)
    for attribute in fields(value):
        with pytest.raises(FrozenInstanceError):
            setattr(value, attribute.name, None)
        with pytest.raises(FrozenInstanceError):
            delattr(value, attribute.name)
    assert all(
        parameter.kind is Parameter.KEYWORD_ONLY
        for parameter in signature(CollectionRequest).parameters.values()
    )
    with pytest.raises(TypeError):
        CollectionRequest("profile", value.target, value.selection)
    with pytest.raises(TypeError):
        CollectionRequest(
            profile_id="profile",
            target=value.target,
            selection=value.selection,
            site_id="not-a-core-field",
        )


def test_request_construction_is_offline_and_does_not_read_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Contract construction must not perform I/O or read runtime state.")

    with monkeypatch.context() as patched:
        for owner, name in (
            (builtins, "open"),
            (io, "open"),
            (Path, "stat"),
            (Path, "resolve"),
            (Path, "expanduser"),
            (socket, "socket"),
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (time, "time"),
            (time, "monotonic"),
            (uuid, "uuid4"),
        ):
            patched.setattr(owner, name, forbidden)
        value = request()
        assert replace(value, execution_control=UntouchedControl()).selection is value.selection
