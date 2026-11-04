"""Synthetic Profile composition and explicit preparatory-versus-active boundaries."""

import ast
import builtins
import io
import socket
import subprocess
import sys
from collections.abc import Hashable
from dataclasses import FrozenInstanceError, fields, replace
from inspect import Parameter, signature
from pathlib import Path
from types import MappingProxyType

import pytest

import nipstack_core
from nipstack_core import NipStackCoreUsageError, ProfileIdentity, contracts, profiles
from nipstack_core.profiles import (
    ArtifactDefinition,
    CLIActionDefinition,
    CLIContextDefinition,
    ConnectionDefinition,
    FeatureDefinition,
    FingerprintDefinition,
    HTTPActionDefinition,
    HTTPRequestDefinition,
    ParserDefinition,
    ProfileDefinition,
    ProfileMetadata,
)


def metadata() -> ProfileMetadata:
    return ProfileMetadata(
        name="Example Switch",
        vendor="example",
        platform_id="example.switch",
        access_variant="cli",
    )


def feature() -> FeatureDefinition:
    return FeatureDefinition(
        feature_id="check.global.show_version",
        inputs=["show_version"],
        parser=ParserDefinition(engine="native", template="features/version/parser.yaml"),
        schema="features/version/schema.json",
    )


def cli_profile() -> ProfileDefinition:
    action = CLIActionDefinition(
        action_id="show_version",
        command="show version",
        artifact=ArtifactDefinition(kind="command_output"),
    )
    observed = feature()
    return ProfileDefinition(
        profile_id="example.switch.cli",
        version="1.0.0",
        metadata=metadata(),
        connection=ConnectionDefinition(connector="ssh", driver="example_cli"),
        actions={action.action_id: action},
        features={observed.feature_id: observed},
        fingerprint=FingerprintDefinition(action_id="show_version", include=["ExampleOS"]),
    )


def http_profile() -> ProfileDefinition:
    action = HTTPActionDefinition(
        action_id="read_status",
        request=HTTPRequestDefinition(
            path="/api/status",
            query=[("item", "first"), ("item", "second")],
            headers={"Accept": "application/json"},
        ),
        artifact=ArtifactDefinition(kind="api_response"),
    )
    observed = replace(
        feature(),
        inputs=["read_status"],
        parser=ParserDefinition(engine="jmespath", template="features/version/parser.jmespath"),
    )
    return ProfileDefinition(
        profile_id="example.switch.api",
        version="1.0.0",
        metadata=replace(metadata(), name="Example Switch API", access_variant="api"),
        connection=ConnectionDefinition(connector="http", authentication="basic"),
        actions={action.action_id: action},
        features={observed.feature_id: observed},
    )


def test_synthetic_ssh_and_http_profiles_share_explicit_platform_and_feature_identity() -> None:
    cli = cli_profile()
    api = http_profile()
    assert cli.metadata.platform_id == api.metadata.platform_id == "example.switch"
    assert list(cli.features) == list(api.features) == ["check.global.show_version"]
    assert cli.features["check.global.show_version"].parser.engine == "native"
    assert api.features["check.global.show_version"].parser.engine == "jmespath"
    assert cli.connection.connector == "ssh"
    assert api.connection.connector == "http"
    assert cli.fingerprint.action_id == "show_version"
    assert api.fingerprint is None
    assert cli.spec_version == api.spec_version == 1


@pytest.mark.parametrize("identifier", ["example", "example.switch", "a.b.c.d", "a_1.b_2"])
def test_profile_and_platform_ids_are_segmented_without_fixed_segment_count(
    identifier: str,
) -> None:
    assert replace(cli_profile(), profile_id=identifier).profile_id == identifier
    assert replace(metadata(), platform_id=identifier).platform_id == identifier


@pytest.mark.parametrize("identifier", ["", "A", "1a", "a-b", "a..b", ".a", "a.", "é", None, 1])
def test_invalid_profile_and_platform_ids_fail(identifier: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(cli_profile(), profile_id=identifier)
    with pytest.raises(NipStackCoreUsageError):
        replace(metadata(), platform_id=identifier)


def test_profile_id_segments_never_infer_transport_vendor_or_access_variant() -> None:
    value = replace(http_profile(), profile_id="unrelated.cli", metadata=metadata())
    assert value.connection.connector == "http"
    assert value.metadata.access_variant == "cli"
    assert value.metadata.vendor == "example"
    public = ProfileIdentity(profile_id="vendor/model @ local", version="not-semver")
    assert public.version == "not-semver"


@pytest.mark.parametrize(
    "version",
    [
        "0.0.0",
        "1.2.3",
        "1.2.3-alpha.1",
        "1.2.3-0",
        "1.2.3-01a",
        "1.2.3-alpha-01",
        "1.2.3+build.001",
        "1.2.3-rc.1+build.001",
        "9" * 5000 + ".0.0",
    ],
)
def test_semver_is_exact_and_preserved_without_numeric_conversion(version: str) -> None:
    assert replace(cli_profile(), version=version).version == version


@pytest.mark.parametrize(
    "version",
    [
        None,
        1,
        "",
        "1",
        "1.0",
        "v1.0.0",
        "01.0.0",
        "1.00.0",
        "1.0.01",
        "1.0.0-01",
        "1.0.0-a.01",
        "1.0.0-",
        "1.0.0+",
        "1.0.0-a..b",
        "1.0.0+a..b",
        "1.0.0-α",
        "1.0.0\n",
        " 1.0.0",
        "1.0.0.1",
        "1.0.0-a_b",
    ],
)
def test_invalid_semver_does_not_become_a_valid_definition(version: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(cli_profile(), version=version)


@pytest.mark.parametrize("value", [True, False, 0, 2, 1.0, "1", None])
def test_spec_version_is_exactly_integer_one_without_bool_coercion(value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(cli_profile(), spec_version=value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", ""),
        ("name", " leading"),
        ("vendor", "trailing "),
        ("vendor", "\ud800"),
        ("vendor", "a\nb"),
        ("access_variant", "two.segments"),
        ("access_variant", "Api"),
        ("access_variant", None),
    ],
)
def test_metadata_fields_are_mandatory_and_locally_validated(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(metadata(), **{field: value})


def test_connection_allows_absent_or_unknown_lexical_selectors_without_capability_claims() -> None:
    ssh = ConnectionDefinition(connector="ssh")
    http = ConnectionDefinition(connector="http", authentication="future_vendor")
    assert ssh.driver is ssh.authentication is None
    assert ssh.session_setup == ()
    assert http.authentication == "future_vendor"
    assert ConnectionDefinition(connector="ssh", driver="future_vendor").driver == "future_vendor"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"connector": "https"},
        {"connector": None},
        {"connector": "SSH"},
        {"connector": "ssh", "authentication": "basic"},
        {"connector": "http", "driver": "vendor"},
        {"connector": "http", "session_setup": ["show version"]},
        {"connector": "ssh", "driver": "a.b"},
        {"connector": "http", "authentication": "a-b"},
        {"connector": "ssh", "session_setup": "show version"},
    ],
)
def test_connection_rejects_local_transport_and_field_mismatches(kwargs: dict[str, object]) -> None:
    with pytest.raises(NipStackCoreUsageError):
        ConnectionDefinition(**kwargs)


def test_setup_and_fingerprint_sequences_are_owned_without_matching_or_deduplication() -> None:
    setup = ["exit", "exit"]
    include = ["ExampleOS", "ExampleOS"]
    exclude = ["not an official match"]
    connection = ConnectionDefinition(connector="ssh", session_setup=setup)
    fingerprint = FingerprintDefinition(action_id="absent", include=include, exclude=exclude)
    setup.clear()
    include.clear()
    exclude.clear()
    assert connection.session_setup == ("exit", "exit")
    assert fingerprint.include == ("ExampleOS", "ExampleOS")
    assert fingerprint.exclude == ("not an official match",)
    assert not hasattr(fingerprint, "match")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action_id": "a.b", "include": ["x"]},
        {"action_id": "a", "include": []},
        {"action_id": "a", "include": "x"},
        {"action_id": "a", "include": [None]},
        {"action_id": "a", "include": ["x"], "exclude": ["\n"]},
    ],
)
def test_invalid_fingerprint_declarations_fail(kwargs: dict[str, object]) -> None:
    with pytest.raises(NipStackCoreUsageError):
        FingerprintDefinition(**kwargs)


@pytest.mark.parametrize("field", ["connect_timeout", "operation_timeout"])
@pytest.mark.parametrize("timeout", [None, 1, 0.25])
def test_profile_timeout_defaults_reuse_existing_optional_seconds(
    field: str, timeout: object
) -> None:
    connection = ConnectionDefinition(connector="ssh", **{field: timeout})
    assert getattr(connection, field) == timeout
    if timeout is not None:
        assert type(getattr(connection, field)) is float


@pytest.mark.parametrize("field", ["connect_timeout", "operation_timeout"])
@pytest.mark.parametrize(
    "timeout",
    [True, 0, -1, float("nan"), float("inf"), pytest.param(10**10000, id="oversized")],
)
def test_invalid_profile_timeout_defaults_fail(field: str, timeout: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        ConnectionDefinition(connector="ssh", **{field: timeout})


@pytest.mark.parametrize(
    "field,value",
    [
        ("metadata", {}),
        ("connection", {}),
        ("fingerprint", {}),
        ("actions", []),
        ("features", []),
        ("actions", {"wrong": next(iter(cli_profile().actions.values()))}),
        ("actions", {"action": feature()}),
        ("actions", {1: next(iter(cli_profile().actions.values()))}),
        ("features", {"wrong": feature()}),
        ("features", {1: feature()}),
        ("features", {"check.global.show_version": next(iter(cli_profile().actions.values()))}),
    ],
)
def test_profile_checks_contained_types_and_key_identity(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(cli_profile(), **{field: value})


def test_primary_connector_must_match_every_action_type() -> None:
    with pytest.raises(NipStackCoreUsageError, match="primary Connector"):
        replace(cli_profile(), actions=http_profile().actions)
    with pytest.raises(NipStackCoreUsageError, match="primary Connector"):
        replace(http_profile(), actions=cli_profile().actions)


def test_typed_profiles_are_not_cross_reference_complete_or_active() -> None:
    dangling = replace(feature(), inputs=["absent", "another_absent"])
    value = replace(
        cli_profile(),
        actions={},
        features={dangling.feature_id: dangling},
        fingerprint=FingerprintDefinition(action_id="absent", include=["ExampleOS"]),
    )
    assert value.actions == {}
    assert value.features[dangling.feature_id].inputs == ("absent", "another_absent")
    assert replace(value, features={}).features == {}
    for keyword in ("validated", "skip_validation", "active", "registry", "source", "target"):
        assert not hasattr(value, keyword)
        with pytest.raises(TypeError):
            replace(value, **{keyword: True})


def test_profile_maps_own_storage_preserve_order_and_allow_shared_multi_input_actions() -> None:
    base = cli_profile()
    action = next(iter(base.actions.values()))
    second_action = replace(action, action_id="second")
    first_feature = replace(feature(), inputs=["show_version", "second"])
    second_feature = replace(first_feature, feature_id="custom.global.other")
    actions = {action.action_id: action, second_action.action_id: second_action}
    features = {first_feature.feature_id: first_feature, second_feature.feature_id: second_feature}
    value = replace(base, actions=MappingProxyType(actions), features=MappingProxyType(features))
    actions.clear()
    features.clear()
    assert list(value.actions) == ["show_version", "second"]
    assert list(value.features) == [first_feature.feature_id, second_feature.feature_id]
    assert (
        value.features[first_feature.feature_id].inputs
        == value.features[second_feature.feature_id].inputs
    )
    reordered = replace(
        value,
        actions=dict(reversed(list(value.actions.items()))),
        features=dict(reversed(list(value.features.items()))),
    )
    assert value == reordered
    with pytest.raises(TypeError):
        value.actions["changed"] = action
    with pytest.raises(TypeError):
        value.features["changed"] = first_feature


MODELS = [
    ArtifactDefinition(kind="custom"),
    CLIContextDefinition(),
    next(iter(cli_profile().actions.values())),
    HTTPRequestDefinition(path="/"),
    next(iter(http_profile().actions.values())),
    ParserDefinition(engine="native", template="parser.yaml"),
    feature(),
    metadata(),
    ConnectionDefinition(connector="ssh"),
    FingerprintDefinition(action_id="a", include=["x"]),
    cli_profile(),
]


@pytest.mark.parametrize("value", MODELS)
def test_every_model_is_frozen_slotted_structurally_equal_and_explicitly_unhashable(
    value: object,
) -> None:
    assert value == replace(value)
    assert not isinstance(value, Hashable)
    assert not hasattr(value, "__dict__")
    with pytest.raises(TypeError):
        hash(value)
    for attribute in fields(value):
        with pytest.raises(FrozenInstanceError):
            setattr(value, attribute.name, None)
    assert all(p.kind is Parameter.KEYWORD_ONLY for p in signature(type(value)).parameters.values())
    with pytest.raises(TypeError):
        type(value)("unexpected")


def test_exact_internal_import_surface_does_not_change_public_exports() -> None:
    expected = {
        "ActionDefinition",
        "ArtifactDefinition",
        "CLIActionDefinition",
        "CLIContextDefinition",
        "HTTPRequestDefinition",
        "HTTPActionDefinition",
        "ParserDefinition",
        "FeatureDefinition",
        "ProfileMetadata",
        "ConnectionDefinition",
        "FingerprintDefinition",
        "ProfileDefinition",
    }
    assert set(profiles.__all__) == expected
    assert not expected.intersection(nipstack_core.__all__)
    assert len(nipstack_core.__all__) == len(contracts.__all__) == 33
    assert set(nipstack_core.__all__) == set(contracts.__all__)
    assert not hasattr(profiles, "ScopeHint")
    assert not hasattr(nipstack_core, "collect")
    signatures = {
        ArtifactDefinition: {"kind", "expose_by_default"},
        CLIContextDefinition: {"enter", "exit"},
        CLIActionDefinition: {"action_id", "command", "artifact", "context", "operation_timeout"},
        HTTPRequestDefinition: {"path", "method", "query", "headers", "body"},
        HTTPActionDefinition: {"action_id", "request", "artifact", "operation_timeout"},
        ParserDefinition: {"engine", "template"},
        FeatureDefinition: {"feature_id", "inputs", "parser", "schema"},
        ProfileMetadata: {"name", "vendor", "platform_id", "access_variant"},
        ConnectionDefinition: {
            "connector",
            "driver",
            "authentication",
            "session_setup",
            "connect_timeout",
            "operation_timeout",
        },
        FingerprintDefinition: {"action_id", "include", "exclude"},
        ProfileDefinition: {
            "profile_id",
            "version",
            "metadata",
            "connection",
            "actions",
            "features",
            "spec_version",
            "fingerprint",
        },
    }
    for model, parameters in signatures.items():
        assert set(signature(model).parameters) == parameters


def test_internal_import_graph_is_acyclic_and_has_no_runtime_or_serializer_dependencies() -> None:
    code = """
import importlib
for name in (
    'nipstack_core.profiles.profile', 'nipstack_core.profiles.features',
    'nipstack_core.profiles.actions', 'nipstack_core.contracts',
):
    importlib.import_module(name)
print('PASS')
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.stdout.strip() == "PASS"
    root = Path(profiles.__file__).parent
    for name in ("actions.py", "features.py", "profile.py"):
        tree = ast.parse((root / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "serialization" not in module
                assert not any(
                    component in module.split(".")
                    for component in (
                        "connectors",
                        "parsers",
                        "execution",
                        "planning",
                        "catalog",
                    )
                )


def test_profile_construction_is_offline_and_does_not_resolve_resource_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Model construction must not perform I/O.")

    with monkeypatch.context() as patched:
        patched.setattr(builtins, "open", forbidden)
        patched.setattr(io, "open", forbidden)
        patched.setattr(Path, "read_text", forbidden)
        patched.setattr(Path, "read_bytes", forbidden)
        patched.setattr(Path, "resolve", forbidden)
        patched.setattr(Path, "stat", forbidden)
        patched.setattr(socket, "socket", forbidden)
        patched.setattr(socket, "create_connection", forbidden)
        patched.setattr(socket, "getaddrinfo", forbidden)
        cli_profile()
        http_profile()


def test_profile_display_and_validation_failures_do_not_echo_private_configuration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    value = replace(
        cli_profile(),
        profile_id="synthetic_private",
        version="1.0.0+SYNTHETIC-PRIVATE",
        metadata=replace(metadata(), name="SYNTHETIC_PRIVATE", vendor="SYNTHETIC_PRIVATE"),
        connection=ConnectionDefinition(connector="ssh", session_setup=["SYNTHETIC_PRIVATE"]),
        fingerprint=FingerprintDefinition(
            action_id="synthetic_private", include=["SYNTHETIC_PRIVATE"]
        ),
    )
    for part in (value, value.metadata, value.connection, value.fingerprint):
        assert "SYNTHETIC_PRIVATE" not in str(part) + repr(part)
        assert "SYNTHETIC-PRIVATE" not in str(part) + repr(part)
        assert "synthetic_private" not in str(part) + repr(part)
    for field in (
        "profile_id",
        "version",
        "metadata",
        "connection",
        "actions",
        "features",
        "fingerprint",
    ):
        with pytest.raises(NipStackCoreUsageError) as caught:
            replace(cli_profile(), **{field: "SYNTHETIC_PRIVATE\n"})
        assert "SYNTHETIC_PRIVATE" not in str(caught.value)
    assert not caplog.records
