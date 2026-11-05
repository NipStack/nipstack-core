"""Strict manifest mapping, nullability, cross-references and immutable offline loading."""

import builtins
import copy
import json
import os
import socket
import subprocess
from collections.abc import Hashable
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from types import MappingProxyType

import pytest

import nipstack_core
from nipstack_core import contracts, profiles
from nipstack_core.profiles import loader
from nipstack_core.profiles.loader import LoadedProfile, LoadLimits, ProfileLoadError, load_profile

ACTION = "read_version"
FEATURE = "check.global.show_version"
RESOURCES = {"resources/parser.data": b"\xffopaque parser", "resources/schema.data": b"not JSON"}


def manifest(transport: str = "ssh") -> dict[str, object]:
    action: dict[str, object] = {
        "type": "cli" if transport == "ssh" else "http",
        "artifact": {"kind": "command_output" if transport == "ssh" else "api_response"},
    }
    if transport == "ssh":
        action["command"] = "show version"
    else:
        action["request"] = {"path": "/api/version"}
    return {
        "spec_version": 1,
        "id": "example.switch.cli" if transport == "ssh" else "example.switch.api",
        "version": "1.0.0",
        "metadata": {
            "name": "Example Switch",
            "vendor": "example",
            "platform_id": "example.switch",
            "access_variant": "cli" if transport == "ssh" else "api",
        },
        "connection": {"connector": transport},
        "actions": {ACTION: action},
        "features": {
            FEATURE: {
                "inputs": [ACTION],
                "parser": {
                    "engine": "native" if transport == "ssh" else "jmespath",
                    "template": "resources/parser.data",
                },
                "schema": "resources/schema.data",
            }
        },
    }


def at(document: dict[str, object], path: tuple[str, ...]) -> dict[str, object]:
    current = document
    for key in path:
        child = current[key]
        assert isinstance(child, dict)
        current = child
    return current


def write_profile(root: Path, document: dict[str, object]) -> Path:
    (root / "profile.yaml").write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    for reference, content in RESOURCES.items():
        file = root / reference
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
    return root


@pytest.mark.parametrize("transport", ["ssh", "http"])
def test_real_models_and_opaque_snapshots_are_loaded(tmp_path: Path, transport: str) -> None:
    result = load_profile(write_profile(tmp_path, manifest(transport)))
    assert result.definition.connection.connector == transport
    assert result.definition.actions[ACTION].action_id == ACTION
    assert result.definition.features[FEATURE].feature_id == FEATURE
    assert result.definition.features[FEATURE].inputs == (ACTION,)
    assert dict(result.resources) == RESOURCES
    assert list(result.resources) == list(RESOURCES)
    assert result.definition.fingerprint is None
    assert result == load_profile(tmp_path)
    assert not isinstance(result, Hashable)
    assert not hasattr(result, "__dict__")
    assert not hasattr(result.definition, "validated")
    assert not hasattr(result.definition, "active")


def test_complete_cli_context_connection_and_fingerprint(tmp_path: Path) -> None:
    document = manifest()
    document["connection"] = {
        "connector": "ssh",
        "driver": "unknown_but_lexical",
        "authentication": None,
        "session_setup": ["prepare", "prepare"],
        "connect_timeout": 2,
        "operation_timeout": 5.5,
    }
    action = at(document, ("actions", ACTION))
    action["context"] = {"enter": ["enter"], "exit": ["exit", "exit"]}
    action["operation_timeout"] = 3
    action["artifact"] = {"kind": "custom", "expose_by_default": True}
    document["identification"] = {
        "action": ACTION,
        "match": {"include": ["ExampleOS"], "exclude": ["Excluded"]},
    }
    result = load_profile(write_profile(tmp_path, document)).definition
    assert result.connection.driver == "unknown_but_lexical"
    assert result.connection.session_setup == ("prepare", "prepare")
    assert result.connection.connect_timeout == 2.0
    assert result.actions[ACTION].context.exit == ("exit", "exit")
    assert result.actions[ACTION].artifact.expose_by_default is True
    assert result.actions[ACTION].operation_timeout == 3.0
    assert result.fingerprint.include == ("ExampleOS",)
    assert result.fingerprint.exclude == ("Excluded",)


@pytest.mark.parametrize("body", [None, {}, [], {"items": [{"enabled": True}], "scope": "payload"}])
def test_http_post_body_query_and_headers_are_adapted_without_encoding(
    tmp_path: Path, body: object
) -> None:
    document = manifest("http")
    request = at(document, ("actions", ACTION, "request"))
    request.update(
        {
            "method": "POST",
            "body": body,
            "query": [["item", "a/b"], ["item", "c+d"], ["empty", ""], ["filter", "a b&é"]],
            "headers": {"Accept": "application/vendor+json", "Content-Type": "text/plain"},
        }
    )
    result = load_profile(write_profile(tmp_path, document))
    request_model = result.definition.actions[ACTION].request
    assert request_model.query == (
        ("item", "a/b"),
        ("item", "c+d"),
        ("empty", ""),
        ("filter", "a b&é"),
    )
    assert request_model.headers["Content-Type"] == "text/plain"
    if body is None:
        assert request_model.body is None
    else:
        assert request_model.body is not None


NULLABLE = [
    ("ssh", (), "identification"),
    ("ssh", ("connection",), "driver"),
    ("http", ("connection",), "authentication"),
    ("ssh", ("connection",), "connect_timeout"),
    ("ssh", ("connection",), "operation_timeout"),
    ("ssh", ("actions", ACTION), "context"),
    ("ssh", ("actions", ACTION), "operation_timeout"),
    ("http", ("actions", ACTION), "operation_timeout"),
    ("http", ("actions", ACTION, "request"), "query"),
    ("http", ("actions", ACTION, "request"), "headers"),
    ("http", ("actions", ACTION, "request"), "body"),
]


@pytest.mark.parametrize(("transport", "path", "key"), NULLABLE)
def test_explicit_null_matches_approved_absent_defaults(
    tmp_path: Path, transport: str, path: tuple[str, ...], key: str
) -> None:
    document = manifest(transport)
    absent = load_profile(write_profile(tmp_path, document))
    at(document, path)[key] = None
    assert load_profile(write_profile(tmp_path, document)) == absent


NONNULL = [
    ("ssh", ("connection",), "session_setup", []),
    ("ssh", ("actions", ACTION, "context"), "enter", []),
    ("ssh", ("actions", ACTION, "context"), "exit", []),
    ("ssh", ("actions", ACTION, "artifact"), "expose_by_default", False),
    ("http", ("actions", ACTION, "request"), "method", "GET"),
    ("ssh", ("identification", "match"), "exclude", []),
]


@pytest.mark.parametrize(("transport", "path", "key", "empty"), NONNULL)
def test_nonnullable_defaults_do_not_replace_explicit_null(
    tmp_path: Path, transport: str, path: tuple[str, ...], key: str, empty: object
) -> None:
    document = manifest(transport)
    at(document, ("actions", ACTION))["context"] = {} if transport == "ssh" else None
    if transport == "http":
        at(document, ("actions", ACTION)).pop("context")
    document["identification"] = {"action": ACTION, "match": {"include": ["ExampleOS"]}}
    absent = load_profile(write_profile(tmp_path, document))
    at(document, path)[key] = empty
    assert load_profile(write_profile(tmp_path, document)) == absent
    at(document, path)[key] = None
    with pytest.raises(ProfileLoadError) as failure:
        load_profile(write_profile(tmp_path, document))
    assert failure.value.code == "INVALID_MANIFEST"


REQUIRED = (
    [
        ((), key)
        for key in (
            "spec_version",
            "id",
            "version",
            "metadata",
            "connection",
            "actions",
            "features",
        )
    ]
    + [(("metadata",), key) for key in ("name", "vendor", "platform_id", "access_variant")]
    + [
        (("connection",), "connector"),
        (("actions", ACTION), "type"),
        (("actions", ACTION), "command"),
        (("actions", ACTION), "artifact"),
        (("actions", ACTION, "artifact"), "kind"),
        (("features", FEATURE), "inputs"),
        (("features", FEATURE), "parser"),
        (("features", FEATURE), "schema"),
        (("features", FEATURE, "parser"), "engine"),
        (("features", FEATURE, "parser"), "template"),
        (("identification",), "action"),
        (("identification",), "match"),
        (("identification", "match"), "include"),
    ]
)


@pytest.mark.parametrize(("path", "key"), REQUIRED)
@pytest.mark.parametrize("missing", [False, True])
def test_required_fields_reject_absence_and_null(
    tmp_path: Path, path: tuple[str, ...], key: str, missing: bool
) -> None:
    document = manifest()
    document["identification"] = {"action": ACTION, "match": {"include": ["ExampleOS"]}}
    if missing:
        del at(document, path)[key]
    else:
        at(document, path)[key] = None
    with pytest.raises(ProfileLoadError) as failure:
        load_profile(write_profile(tmp_path, document))
    assert failure.value.code == "INVALID_MANIFEST"


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("metadata",),
        ("connection",),
        ("actions", ACTION),
        ("actions", ACTION, "artifact"),
        ("actions", ACTION, "context"),
        ("features", FEATURE),
        ("features", FEATURE, "parser"),
        ("identification",),
        ("identification", "match"),
    ],
)
def test_unknown_fields_fail_at_every_closed_level(tmp_path: Path, path: tuple[str, ...]) -> None:
    document = manifest()
    at(document, ("actions", ACTION))["context"] = {}
    document["identification"] = {"action": ACTION, "match": {"include": ["ExampleOS"]}}
    at(document, path)["SYNTHETIC_PRIVATE"] = "SYNTHETIC_PRIVATE"
    with pytest.raises(ProfileLoadError) as failure:
        load_profile(write_profile(tmp_path, document))
    assert failure.value.code == "INVALID_MANIFEST"
    assert "SYNTHETIC_PRIVATE" not in repr(failure.value) + str(failure.value)
    assert "SYNTHETIC_PRIVATE" not in (failure.value.field or "")


@pytest.mark.parametrize("path", [("actions", ACTION), ("actions", ACTION, "request")])
def test_http_closed_levels_and_required_request_path(
    tmp_path: Path, path: tuple[str, ...]
) -> None:
    document = manifest("http")
    at(document, path)["unknown"] = True
    with pytest.raises(ProfileLoadError):
        load_profile(write_profile(tmp_path, document))
    del at(document, path)["unknown"]
    del at(document, ("actions", ACTION, "request"))["path"]
    with pytest.raises(ProfileLoadError):
        load_profile(write_profile(tmp_path, document))


@pytest.mark.parametrize(
    "key",
    [
        "scope",
        "scope_hint",
        "management_system",
        "managed_system",
        "source_type",
        "depends_on",
        "command",
        "feature_id",
    ],
)
def test_removed_feature_classification_and_extra_fields_fail(tmp_path: Path, key: str) -> None:
    document = manifest()
    at(document, ("features", FEATURE))[key] = "SOURCE"
    with pytest.raises(ProfileLoadError):
        load_profile(write_profile(tmp_path, document))


@pytest.mark.parametrize(
    ("path", "key", "value"),
    [
        ((), "spec_version", True),
        ((), "spec_version", 1.0),
        ((), "spec_version", 2),
        ((), "version", "01.0.0"),
        ((), "version", 1),
        ((), "id", "Invalid"),
        ((), "actions", []),
        ((), "features", []),
        ((), "metadata", "wrong"),
        (("connection",), "connector", "unknown"),
        (("connection",), "connect_timeout", True),
        (("connection",), "connect_timeout", "5"),
        (("connection",), "operation_timeout", 0),
        (("connection",), "session_setup", "command"),
        (("actions", ACTION), "type", "http"),
        (("actions", ACTION), "command", 1),
        (("actions", ACTION), "action_id", "mismatch"),
        (("features", FEATURE), "inputs", []),
        (("features", FEATURE), "inputs", [ACTION, ACTION]),
        (("features", FEATURE), "inputs", ACTION),
        (("features", FEATURE), "schema", {"type": "object"}),
        (("features", FEATURE, "parser"), "engine", "ttp"),
        (("features", FEATURE, "parser"), "template", "../escape"),
        (("features", FEATURE, "parser"), "template", "/absolute"),
    ],
)
def test_wrong_types_and_local_invariants_reuse_real_models(
    tmp_path: Path, path: tuple[str, ...], key: str, value: object
) -> None:
    document = manifest()
    at(document, path)[key] = value
    with pytest.raises(ProfileLoadError) as failure:
        load_profile(write_profile(tmp_path, document))
    assert failure.value.code == "INVALID_MANIFEST"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("method", "DELETE"),
        ("method", False),
        ("body", {}),
        ("body", []),
        ("query", {"item": "one"}),
        ("query", [["item", 1]]),
        ("query", [["item"]]),
        ("query", [["item", "one", "two"]]),
        ("query", [["", "one"]]),
        ("query", [["item", "one\n"]]),
        ("headers", {"Authorization": "synthetic"}),
        ("headers", {"Accept": 1}),
        ("headers", {"Accept": "one", "accept": "two"}),
        ("path", "https://example.invalid/x"),
    ],
)
def test_http_mapping_preserves_30a_rejections(tmp_path: Path, key: str, value: object) -> None:
    document = manifest("http")
    at(document, ("actions", ACTION, "request"))[key] = value
    with pytest.raises(ProfileLoadError) as failure:
        load_profile(write_profile(tmp_path, document))
    assert failure.value.code == "INVALID_MANIFEST"


def test_empty_mappings_are_loaded_but_not_activated(tmp_path: Path) -> None:
    document = manifest()
    document.update({"actions": {}, "features": {}})
    result = load_profile(write_profile(tmp_path, document))
    assert result.resources == {}
    assert result.definition.actions == result.definition.features == {}


@pytest.mark.parametrize("fingerprint", [False, True])
def test_unknown_action_references_fail(tmp_path: Path, fingerprint: bool) -> None:
    document = manifest()
    if fingerprint:
        document["identification"] = {"action": "absent", "match": {"include": ["ExampleOS"]}}
    else:
        at(document, ("features", FEATURE))["inputs"] = ["absent"]
    with pytest.raises(ProfileLoadError) as failure:
        load_profile(write_profile(tmp_path, document))
    assert failure.value.code == "INVALID_REFERENCE"


def test_shared_inputs_resources_and_order_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = manifest()
    actions = at(document, ("actions",))
    actions["second"] = copy.deepcopy(actions[ACTION])
    features = at(document, ("features",))
    at(document, ("features", FEATURE))["inputs"] = ["second", ACTION]
    features["custom.global.other"] = copy.deepcopy(features[FEATURE])
    root = write_profile(tmp_path, document)
    reads: list[str] = []
    original = loader._read_regular_file

    def tracked(descriptor, reference, **kwargs):
        reads.append(reference)
        return original(descriptor, reference, **kwargs)

    monkeypatch.setattr(loader, "_read_regular_file", tracked)
    result = load_profile(root, limits=LoadLimits(max_resource_files=2))
    assert reads == ["profile.yaml", *RESOURCES]
    assert list(result.definition.actions) == [ACTION, "second"]
    assert list(result.definition.features) == [FEATURE, "custom.global.other"]
    assert result.definition.features[FEATURE].inputs == ("second", ACTION)


@pytest.mark.parametrize("budget", [field.name for field in fields(LoadLimits)])
@pytest.mark.parametrize("value", [None, True, False, 0, -1, 1.0, "1"])
def test_limits_are_strict_positive_integers(budget: str, value: object) -> None:
    with pytest.raises(ProfileLoadError) as failure:
        LoadLimits(**{budget: value})
    assert failure.value.code == "INVALID_ARGUMENT"
    assert failure.value.field == budget


def test_limit_defaults_immutability_and_independent_overlapping_ceilings() -> None:
    limits = LoadLimits()
    assert [getattr(limits, field.name) for field in fields(limits)] == [
        1_048_576,
        2_097_152,
        16_777_216,
        80,
        100_000,
        65_536,
        256,
        1_024,
        2_048,
        32,
        512,
    ]
    assert LoadLimits(max_total_bytes=1, max_manifest_bytes=100).max_manifest_bytes == 100
    with pytest.raises(FrozenInstanceError):
        limits.max_total_bytes = 1


@pytest.mark.parametrize("budget", ["max_actions", "max_features", "max_resource_files"])
@pytest.mark.parametrize("limit", [1, 2, 3])
def test_count_budgets_have_exact_boundaries(tmp_path: Path, budget: str, limit: int) -> None:
    document = manifest()
    if budget == "max_actions":
        at(document, ("actions",))["second"] = copy.deepcopy(at(document, ("actions", ACTION)))
    elif budget == "max_features":
        at(document, ("features",))["custom.global.other"] = copy.deepcopy(
            at(document, ("features", FEATURE))
        )
    write_profile(tmp_path, document)
    if limit < 2:
        with pytest.raises(ProfileLoadError) as failure:
            load_profile(tmp_path, limits=LoadLimits(**{budget: limit}))
        assert failure.value.code == "RESOURCE_LIMIT"
    else:
        load_profile(tmp_path, limits=LoadLimits(**{budget: limit}))


@pytest.mark.parametrize("budget", ["max_manifest_bytes", "max_resource_bytes", "max_total_bytes"])
@pytest.mark.parametrize("difference", [-1, 0, 1])
def test_byte_budgets_have_exact_boundaries(tmp_path: Path, budget: str, difference: int) -> None:
    write_profile(tmp_path, manifest())
    manifest_size = (tmp_path / "profile.yaml").stat().st_size
    threshold = {
        "max_manifest_bytes": manifest_size,
        "max_resource_bytes": max(map(len, RESOURCES.values())),
        "max_total_bytes": manifest_size + sum(map(len, RESOURCES.values())),
    }[budget]
    limits = LoadLimits(**{budget: threshold + difference})
    if difference < 0:
        with pytest.raises(ProfileLoadError) as failure:
            load_profile(tmp_path, limits=limits)
        assert failure.value.code == "RESOURCE_LIMIT"
    else:
        load_profile(tmp_path, limits=limits)


def test_manifest_reused_as_resource_is_counted_and_read_once(tmp_path: Path) -> None:
    document = manifest()
    at(document, ("features", FEATURE, "parser"))["template"] = "profile.yaml"
    at(document, ("features", FEATURE))["schema"] = "profile.yaml"
    write_profile(tmp_path, document)
    content = (tmp_path / "profile.yaml").read_bytes()
    result = load_profile(tmp_path, limits=LoadLimits(max_total_bytes=len(content)))
    assert result.resources == {"profile.yaml": content}
    with pytest.raises(ProfileLoadError):
        load_profile(tmp_path, limits=LoadLimits(max_resource_bytes=len(content) - 1))


def test_distinct_hardlink_references_are_budgeted_separately(tmp_path: Path) -> None:
    write_profile(tmp_path, manifest())
    schema = tmp_path / "resources" / "schema.data"
    schema.unlink()
    os.link(tmp_path / "resources" / "parser.data", schema)
    total = (tmp_path / "profile.yaml").stat().st_size + 2 * len(RESOURCES["resources/parser.data"])
    load_profile(tmp_path, limits=LoadLimits(max_total_bytes=total))
    with pytest.raises(ProfileLoadError) as failure:
        load_profile(tmp_path, limits=LoadLimits(max_total_bytes=total - 1))
    assert failure.value.code == "RESOURCE_LIMIT"


def test_empty_resource_can_fit_an_exhausted_total_budget(tmp_path: Path) -> None:
    write_profile(tmp_path, manifest())
    (tmp_path / "resources" / "schema.data").write_bytes(b"")
    total = (tmp_path / "profile.yaml").stat().st_size + len(RESOURCES["resources/parser.data"])
    loaded = load_profile(tmp_path, limits=LoadLimits(max_total_bytes=total))
    assert loaded.resources["resources/schema.data"] == b""


def test_reference_component_budget_is_wired_to_loading(tmp_path: Path) -> None:
    write_profile(tmp_path, manifest())
    with pytest.raises(ProfileLoadError) as failure:
        load_profile(tmp_path, limits=LoadLimits(max_path_components=1))
    assert failure.value.code == "RESOURCE_LIMIT"
    load_profile(tmp_path, limits=LoadLimits(max_path_components=2))


@pytest.mark.parametrize("depth", [64, 65])
def test_json_depth_is_not_applied_to_the_manifest_wrapper(tmp_path: Path, depth: int) -> None:
    document = manifest("http")
    body = 0
    for _ in range(depth):
        body = [body]
    at(document, ("actions", ACTION, "request")).update({"method": "POST", "body": body})
    write_profile(tmp_path, document)
    if depth == 64:
        load_profile(tmp_path)
    else:
        with pytest.raises(ProfileLoadError) as failure:
            load_profile(tmp_path)
        assert failure.value.code == "INVALID_MANIFEST"


def test_loaded_snapshots_are_owned_immutable_and_not_reread(tmp_path: Path) -> None:
    result = load_profile(write_profile(tmp_path, manifest()))
    for reference in RESOURCES:
        (tmp_path / reference).write_bytes(b"changed")
    (tmp_path / "profile.yaml").unlink()
    assert result.resources == RESOURCES
    caller_owned = dict(RESOURCES)
    copied = LoadedProfile(definition=result.definition, resources=MappingProxyType(caller_owned))
    caller_owned.clear()
    assert copied == result
    with pytest.raises(TypeError):
        result.resources["new"] = b"data"
    with pytest.raises(FrozenInstanceError):
        result.definition = result.definition
    assert "example.switch.cli" not in repr(result)
    assert "opaque" not in repr(result)


@pytest.mark.parametrize("resources", [None, {"file": bytearray(b"mutable")}, {1: b"data"}])
def test_snapshot_constructor_rejects_nonimmutable_values(
    tmp_path: Path, resources: object
) -> None:
    result = load_profile(write_profile(tmp_path, manifest()))
    with pytest.raises(ProfileLoadError):
        LoadedProfile(definition=result.definition, resources=resources)


def test_loader_has_no_network_or_command_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_profile(tmp_path, manifest("http"))

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Loader must stay offline and never execute commands")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(builtins, "eval", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    load_profile(root)


def test_failure_is_sanitized_deterministic_and_does_not_poison_later_loads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    document = manifest()
    at(document, ("actions", ACTION))["command"] = "SYNTHETIC_PRIVATE\n"
    write_profile(tmp_path, document)
    failures = []
    for _ in range(2):
        with pytest.raises(ProfileLoadError) as failure:
            load_profile(tmp_path)
        error = failure.value
        failures.append((error.code, error.field, error.line, error.column, str(error)))
        assert "SYNTHETIC_PRIVATE" not in str(error) + repr(error) + caplog.text
        assert str(tmp_path) not in str(error) + repr(error)
    assert failures[0] == failures[1]
    load_profile(write_profile(tmp_path, manifest()))


def test_internal_and_public_exports_remain_unchanged() -> None:
    assert len(profiles.__all__) == 12
    assert len(nipstack_core.__all__) == len(contracts.__all__) == 33
    assert "load_profile" not in profiles.__all__
    assert not hasattr(nipstack_core, "LoadedProfile")
    assert not hasattr(nipstack_core, "ScopeHint")
    assert not hasattr(nipstack_core, "collect")


def test_invalid_loader_arguments_and_missing_resources_fail(tmp_path: Path) -> None:
    with pytest.raises(ProfileLoadError) as failure:
        load_profile(tmp_path, limits=None)
    assert failure.value.code == "INVALID_ARGUMENT"
    write_profile(tmp_path, manifest())
    (tmp_path / "resources" / "schema.data").unlink()
    with pytest.raises(ProfileLoadError) as failure:
        load_profile(tmp_path)
    assert failure.value.code == "IO_ERROR"
