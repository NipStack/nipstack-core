"""Synthetic declarative Action validation, never transport or request encoding."""

import json
import sys
from collections.abc import Callable, Hashable
from dataclasses import FrozenInstanceError, fields, replace
from inspect import Parameter, signature
from types import MappingProxyType

import pytest

from nipstack_core import NipStackCoreUsageError, SecretValue
from nipstack_core.profiles import (
    ArtifactDefinition,
    CLIActionDefinition,
    CLIContextDefinition,
    HTTPActionDefinition,
    HTTPRequestDefinition,
)


def cli() -> CLIActionDefinition:
    return CLIActionDefinition(
        action_id="show_version",
        command="show version",
        artifact=ArtifactDefinition(kind="command_output"),
    )


def http() -> HTTPActionDefinition:
    return HTTPActionDefinition(
        action_id="read_status",
        request=HTTPRequestDefinition(path="/api/status"),
        artifact=ArtifactDefinition(kind="api_response"),
    )


@pytest.mark.parametrize(
    "kind", ["command_output", "configuration_snapshot", "api_response", "custom"]
)
def test_artifact_kind_is_open_semantic_metadata_with_no_disclosure_permission(kind: str) -> None:
    value = ArtifactDefinition(kind=kind)
    assert value.kind == kind
    assert value.expose_by_default is False
    assert replace(value, expose_by_default=True).expose_by_default is True
    assert not hasattr(value, "artifact_id")
    assert not hasattr(value, "content_type")


@pytest.mark.parametrize("kind", [None, True, 1, "", "api.response", "Api", "_a", "1a", "a-b", "é"])
def test_artifact_rejects_invalid_semantic_tokens(kind: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        ArtifactDefinition(kind=kind)


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], object()])
def test_artifact_requires_a_real_bool(value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        ArtifactDefinition(kind="custom", expose_by_default=value)


def test_cli_commands_and_context_are_static_owned_ordered_values() -> None:
    enter = ["enter one", "enter two"]
    exit_commands = ["exit", "exit"]
    context = CLIContextDefinition(enter=enter, exit=exit_commands)
    action = replace(cli(), context=context, command="show  version")
    enter.clear()
    exit_commands.clear()
    assert context.enter == ("enter one", "enter two")
    assert context.exit == ("exit", "exit")
    assert action.command == "show  version"
    assert action.context is context
    assert action.type == "cli"
    assert cli().context is None
    assert CLIContextDefinition().enter == CLIContextDefinition().exit == ()
    assert context != replace(context, enter=("enter two", "enter one"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("action_id", "two.segments"),
        ("action_id", None),
        ("action_id", "Upper"),
        ("command", ""),
        ("command", " leading"),
        ("command", "trailing "),
        ("command", "show\nversion"),
        ("command", "show\tversion"),
        ("command", "\ud800"),
        ("command", SecretValue("SYNTHETIC_PRIVATE")),
        ("artifact", {}),
        ("context", {}),
        ("context", ["enter"]),
    ],
)
def test_cli_rejects_invalid_local_fields(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(cli(), **{field: value})


@pytest.mark.parametrize("field", ["enter", "exit"])
@pytest.mark.parametrize("value", [None, "exit", b"exit", {"exit"}, iter(["exit"]), [None], [""]])
def test_context_rejects_invalid_command_sequences(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        CLIContextDefinition(**{field: value})


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_only_approved_methods_are_accepted_without_read_only_claims(method: str) -> None:
    value = HTTPRequestDefinition(path="/status", method=method)
    assert value.method == method
    assert value.body is None
    assert value.query == ()
    assert value.headers == {}
    assert not hasattr(value, "read_only")
    assert not hasattr(value, "to_dict")
    assert not hasattr(value, "to_json")
    assert http().type == "http"


@pytest.mark.parametrize(
    "method", ["PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "get", "", None, 1]
)
def test_unapproved_methods_fail(method: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        HTTPRequestDefinition(path="/status", method=method)


@pytest.mark.parametrize("body", [{}, [], (), {"operation": "read"}, [None]])
def test_get_requires_absent_body_even_when_document_is_empty(body: object) -> None:
    with pytest.raises(NipStackCoreUsageError, match="GET requires body=None"):
        HTTPRequestDefinition(path="/status", body=body)
    post = HTTPRequestDefinition(path="/status", method="POST", body=body)
    assert post.body is not None


@pytest.mark.parametrize("body", [None, {}, [], (), {"items": []}, [True, 1, None]])
def test_post_preserves_missing_versus_present_empty_json(body: object) -> None:
    post = HTTPRequestDefinition(path="/query", method="POST", body=body)
    assert (post.body is None) is (body is None)
    if isinstance(body, (list, tuple)):
        assert isinstance(post.body, tuple)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/api/status",
        "/items/a.b",
        "/a@b;c:d",
        "/utf8/%C3%A9",
        "/literal/%25",
        "/" + "a" * 3000,
    ],
)
def test_relative_uri_paths_have_no_arbitrary_length_ceiling_or_resolution(path: str) -> None:
    assert HTTPRequestDefinition(path=path).path == path


@pytest.mark.parametrize(
    "path",
    [
        None,
        1,
        "",
        "api/status",
        "https://example.invalid/status",
        "//example.invalid/status",
        "/status?token=x",
        "/status#fragment",
        "/a b",
        "/a\\b",
        "/a\nb",
        "/\ud800",
        "/é",
        "/./status",
        "/a/../status",
        "/a/%2e%2E/status",
        "/%2e",
        "/.%2e/",
        "/%2Fstatus",
        "/%5cstatus",
        "/%00",
        "/%0d",
        "/%0A",
        "/%20",
        "/%7F",
        "/%",
        "/%a",
        "/%gg",
    ],
)
def test_unsafe_or_ambiguous_uri_paths_fail_without_echo(path: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        HTTPRequestDefinition(path=path)


@pytest.mark.parametrize("query", [None, [], ()])
def test_missing_or_empty_query_is_an_immutable_empty_tuple(query: object) -> None:
    assert HTTPRequestDefinition(path="/status", query=query).query == ()


def test_query_preserves_order_repetitions_raw_reserved_characters_and_empty_values() -> None:
    pairs = [
        ("item", "a/b"),
        ("item", "c+d"),
        ("filter", "a b&é😀"),
        ("empty", ""),
        ("literal", "%2F"),
        (" name ", " value "),
    ]
    expected = tuple(pairs)
    request = HTTPRequestDefinition(path="/status", query=pairs)
    pairs.clear()
    assert request.query == expected
    assert isinstance(request.query, tuple)
    assert request != replace(request, query=tuple(reversed(expected)))
    assert replace(request, query=[("Item", "x"), ("item", "x")]).query == (
        ("Item", "x"),
        ("item", "x"),
    )


@pytest.mark.parametrize(
    "query",
    [
        "a=b",
        b"a=b",
        {"a": "b"},
        {("a", "b")},
        iter([("a", "b")]),
        [("a",)],
        [("a", "b", "c")],
        [["a", "b"]],
        ["ab"],
        [(None, "b")],
        [("a", 1)],
        [("", "b")],
        [("a", b"b")],
        [("a", "b\n")],
        [("a\0", "b")],
        [("a", "\ud800")],
        [("a", "\x85")],
        [("a", SecretValue("SYNTHETIC_PRIVATE"))],
    ],
)
def test_query_rejects_invalid_structures_without_coercion(query: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        HTTPRequestDefinition(path="/status", query=query)


def test_header_allowlist_preserves_case_and_values_and_owns_storage() -> None:
    original = {"aCcEpT": "application/vendor+json", "Content-Type": "text/plain;\tcharset=utf-8"}
    request = HTTPRequestDefinition(path="/status", headers=MappingProxyType(original))
    original.clear()
    assert request.headers == {
        "aCcEpT": "application/vendor+json",
        "Content-Type": "text/plain;\tcharset=utf-8",
    }
    assert HTTPRequestDefinition(path="/status", headers={"Accept": ""}).headers == {"Accept": ""}
    with pytest.raises(TypeError):
        request.headers["Accept"] = "changed"


@pytest.mark.parametrize(
    "headers",
    [
        [],
        "Accept",
        {"Accept": "a", "accept": "b"},
        {"": "x"},
        {"Ac cept": "x"},
        {"Accept:": "x"},
        {1: "x"},
        {"Accept": None},
        {"Accept": "x\r\ny"},
        {"Accept": "x\0"},
        {"Accept": "é"},
        {"Accept": "\x7f"},
        {"Content-Type": SecretValue("SYNTHETIC_PRIVATE")},
    ],
)
def test_header_syntax_case_duplicates_and_values_are_validated(headers: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        HTTPRequestDefinition(path="/status", headers=headers)


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "authorization",
        "Proxy-Authorization",
        "Cookie",
        "Set-Cookie",
        "Host",
        "Content-Length",
        "Transfer-Encoding",
        "Connection",
        "TE",
        "Trailer",
        "Upgrade",
        "X-API-Key",
        "X-Auth-Token",
        "X-API-Version",
    ],
)
def test_auth_transport_and_unapproved_vendor_headers_cannot_bypass_allowlist(name: str) -> None:
    with pytest.raises(NipStackCoreUsageError, match="allowlist"):
        HTTPRequestDefinition(path="/status", headers={name: "SYNTHETIC_PRIVATE"})
    with pytest.raises(TypeError):
        HTTPRequestDefinition(path="/status", allowed_headers=[name])


def test_declarative_fields_have_no_old_size_budgets_or_early_integer_encoding() -> None:
    integer = 10**5000
    value = HTTPRequestDefinition(
        method="POST",
        path="/" + "p" * 3000,
        headers={"Accept": "a" * 2000},
        body={"text": "x" * 70000, "integer": integer},
    )
    assert value.body["integer"] == integer
    assert len(value.body["text"]) == 70000


def test_http_body_recursively_owns_nested_mappings_arrays_and_shared_subtrees() -> None:
    child = {"items": [{"value": "original"}]}
    original = {"one": child, "two": child}
    request = HTTPRequestDefinition(path="/query", method="POST", body=MappingProxyType(original))
    child["items"][0]["value"] = "changed"
    original.clear()
    assert request.body == {
        "one": {"items": ({"value": "original"},)},
        "two": {"items": ({"value": "original"},)},
    }
    assert request.body["one"] is not request.body["two"]
    with pytest.raises(TypeError):
        request.body["one"]["items"][0]["value"] = "changed"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "not-an-array",
        True,
        1,
        b"{}",
        {"number": float("nan")},
        {"number": float("inf")},
        {"value": "\ud800"},
        {"\udfff": "value"},
        {1: "value"},
        {"bytes": b"x"},
        {"set": {1}},
        {"error": ValueError("SYNTHETIC_PRIVATE")},
        {"secret": SecretValue("SYNTHETIC_PRIVATE")},
    ],
)
def test_body_uses_existing_json_validation_and_refuses_scalar_roots(body: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        HTTPRequestDefinition(path="/query", method="POST", body=body)


@pytest.mark.parametrize("container", [list, tuple, dict])
@pytest.mark.parametrize("depth", [63, 64, 65])
def test_body_depth_reuses_the_exact_64_container_invariant(container: type, depth: int) -> None:
    body = None
    for _ in range(depth):
        body = {"item": body} if container is dict else container([body])
    if depth <= 64:
        HTTPRequestDefinition(path="/query", method="POST", body=body)
    else:
        with pytest.raises(NipStackCoreUsageError, match="64"):
            HTTPRequestDefinition(path="/query", method="POST", body=body)


def test_body_cycles_fail_without_partial_success() -> None:
    body = []
    body.append(body)
    with pytest.raises(NipStackCoreUsageError, match="cycles"):
        HTTPRequestDefinition(path="/query", method="POST", body=body)


@pytest.mark.parametrize("factory", [cli, http])
@pytest.mark.parametrize("timeout", [None, 0.25, 1])
def test_action_timeouts_follow_existing_optional_positive_seconds(
    factory: Callable[[], object],
    timeout: float | None,
) -> None:
    action = replace(factory(), operation_timeout=timeout)
    assert action.operation_timeout == timeout
    if timeout is not None:
        assert type(action.operation_timeout) is float


@pytest.mark.parametrize("factory", [cli, http])
@pytest.mark.parametrize(
    "timeout",
    [True, 0, -1, float("nan"), float("inf"), "1", pytest.param(10**10000, id="oversized")],
)
def test_action_timeouts_reject_invalid_values(
    factory: Callable[[], object], timeout: object
) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(factory(), operation_timeout=timeout)


@pytest.mark.parametrize(
    "field,value",
    [("action_id", "a.b"), ("request", {}), ("artifact", {})],
)
def test_http_action_requires_typed_local_fields(field: str, value: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(http(), **{field: value})


@pytest.mark.parametrize(
    "value",
    [
        ArtifactDefinition(kind="custom"),
        CLIContextDefinition(),
        cli(),
        http(),
        HTTPRequestDefinition(path="/"),
    ],
)
def test_action_models_are_keyword_only_frozen_slotted_equal_and_unhashable(value: object) -> None:
    assert value == replace(value)
    assert not hasattr(value, "__dict__")
    assert not isinstance(value, Hashable)
    with pytest.raises(TypeError):
        hash(value)
    for attribute in fields(value):
        with pytest.raises(FrozenInstanceError):
            setattr(value, attribute.name, None)
    assert all(p.kind is Parameter.KEYWORD_ONLY for p in signature(type(value)).parameters.values())
    with pytest.raises(TypeError):
        type(value)("unexpected")
    if isinstance(value, (CLIActionDefinition, HTTPActionDefinition)):
        with pytest.raises(TypeError):
            type(value)(action_id="a", type="other")


def test_repr_errors_and_logs_do_not_expose_declarative_configuration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    private = "SYNTHETIC_PRIVATE"
    for value in (
        CLIContextDefinition(enter=[private], exit=[private]),
        replace(cli(), action_id="synthetic_private", command=private),
        HTTPRequestDefinition(
            path="/SYNTHETIC_PRIVATE",
            method="POST",
            query=[(private, private)],
            headers={"Accept": private},
            body={private: private},
        ),
        replace(http(), action_id="synthetic_private"),
    ):
        assert private not in str(value) + repr(value)
        assert "synthetic_private" not in str(value) + repr(value)

    class UnsafeDisplay:
        def __str__(self) -> str:
            raise AssertionError("Do not stringify invalid inputs.")

        def __repr__(self) -> str:
            raise AssertionError("Do not display invalid inputs.")

    for field in ("path", "method", "query", "headers", "body"):
        with pytest.raises(NipStackCoreUsageError) as caught:
            replace(HTTPRequestDefinition(path="/", method="POST"), **{field: UnsafeDisplay()})
        assert private not in str(caught.value)
    assert not caplog.records


def test_action_construction_never_encodes_json_or_changes_python_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("No JSON encoding, global settings or credential access.")

    with monkeypatch.context() as patched:
        patched.setattr(json, "dumps", forbidden)
        patched.setattr(sys, "set_int_max_str_digits", forbidden)
        patched.setattr(SecretValue, "reveal", forbidden)
        cli()
        http()
        HTTPRequestDefinition(
            path="/query",
            method="POST",
            query=[("a", "%2F")],
            body={"integer": 10**5000},
        )
        with pytest.raises(NipStackCoreUsageError):
            HTTPRequestDefinition(
                path="/query",
                method="POST",
                body={"secret": SecretValue("SYNTHETIC_PRIVATE")},
            )
