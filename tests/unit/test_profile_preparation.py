"""Pure structural preparation and safe diagnostic projection."""

import builtins
import io
import os
import socket
import subprocess
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from nipstack_core import NipStackCoreUsageError
from nipstack_core.profiles import (
    ArtifactDefinition,
    CLIActionDefinition,
    ConnectionDefinition,
    FeatureDefinition,
    FingerprintDefinition,
    HTTPActionDefinition,
    HTTPRequestDefinition,
    ParserDefinition,
    ProfileDefinition,
    ProfileMetadata,
)
from nipstack_core.profiles._load_types import _MESSAGES as LOAD_MESSAGES
from nipstack_core.profiles._load_types import LoadedProfile, ProfileLoadError
from nipstack_core.profiles.registry import PreparedProfileSet
from nipstack_core.profiles.validation import PreparationIssue, _check_action_references


def candidate(*, http: bool = False) -> LoadedProfile:
    artifact = ArtifactDefinition(kind="api_response" if http else "command_output")
    action = (
        HTTPActionDefinition(
            action_id="read",
            request=HTTPRequestDefinition(path="/status"),
            artifact=artifact,
        )
        if http
        else CLIActionDefinition(action_id="read", command="synthetic read", artifact=artifact)
    )
    feature = FeatureDefinition(
        feature_id="check.global.status",
        inputs=["read"],
        parser=ParserDefinition(engine="jmespath" if http else "native", template="parser.data"),
        schema="schema.data",
    )
    return LoadedProfile(
        definition=ProfileDefinition(
            profile_id="example.http" if http else "example.cli",
            version="1.0.0",
            metadata=ProfileMetadata(
                name="Synthetic", vendor="example", platform_id="example", access_variant="test"
            ),
            connection=ConnectionDefinition(connector="http" if http else "ssh"),
            actions={"read": action},
            features={feature.feature_id: feature},
        ),
        resources={"parser.data": b"\xffnot a parser", "schema.data": b"not JSON"},
    )


@pytest.mark.parametrize("http", [False, True])
def test_real_models_prepare_without_semantic_validation(http: bool) -> None:
    loaded = candidate(http=http)
    prepared = PreparedProfileSet(candidates=[loaded])
    assert prepared.issues == ()
    assert prepared.lookup(loaded.definition.profile_id).profile is loaded
    assert prepared.lookup(loaded.definition.profile_id).status == "PREPARED"


def test_unknown_capabilities_mismatched_engine_and_invalid_fingerprint_are_deferred() -> None:
    loaded = candidate()
    feature = next(iter(loaded.definition.features.values()))
    definition = replace(
        loaded.definition,
        connection=ConnectionDefinition(connector="ssh", driver="unregistered"),
        features={
            feature.feature_id: replace(
                feature, parser=ParserDefinition(engine="jmespath", template="parser.data")
            )
        },
        fingerprint=FingerprintDefinition(action_id="read", include=["["]),
    )
    prepared = PreparedProfileSet(candidates=[replace(loaded, definition=definition)])
    assert prepared.issues == ()
    assert prepared.lookup(definition.profile_id).status == "PREPARED"


@pytest.mark.parametrize("missing", ["parser.data", "schema.data", "both"])
def test_direct_loaded_values_need_all_resource_snapshots(missing: str) -> None:
    loaded = candidate()
    resources = {
        key: value
        for key, value in loaded.resources.items()
        if key != missing and missing != "both"
    }
    direct = replace(loaded, resources=resources)
    prepared = PreparedProfileSet(candidates=[direct, candidate(http=True)])
    issue = prepared.issues[0]
    assert issue.code == "RESOURCE_MISSING"
    assert issue.candidate_indices == (0,)
    assert issue.profile_id == "example.cli"
    assert prepared.lookup("example.cli").status == "INVALID"
    assert prepared.lookup("example.cli").profile is None
    assert prepared.lookup("example.http").status == "PREPARED"


@pytest.mark.parametrize("fingerprint", [False, True])
def test_feature_and_fingerprint_references_reuse_loader_validation(fingerprint: bool) -> None:
    loaded = candidate()
    observed = next(iter(loaded.definition.features.values()))
    definition = replace(
        loaded.definition,
        features=(
            loaded.definition.features
            if fingerprint
            else {observed.feature_id: replace(observed, inputs=["missing"])}
        ),
        fingerprint=FingerprintDefinition(
            action_id="missing" if fingerprint else "read", include=["synthetic"]
        ),
    )
    with pytest.raises(ProfileLoadError) as caught:
        _check_action_references(definition)
    assert caught.value.code == "INVALID_REFERENCE"
    assert caught.value.field == ("identification.action" if fingerprint else "features[0].inputs")
    prepared = PreparedProfileSet(candidates=[replace(loaded, definition=definition, resources={})])
    assert [issue.code for issue in prepared.issues] == ["INVALID_REFERENCE"]
    assert prepared.lookup("example.cli").status == "INVALID"


@pytest.mark.parametrize("contents", [b"", b"\x00\xff", b"invalid syntax"])
def test_resources_stay_opaque_and_extra_entries_are_preserved(contents: bytes) -> None:
    loaded = replace(
        candidate(),
        resources={"parser.data": contents, "schema.data": contents, "extra.data": b"extra"},
    )
    prepared = PreparedProfileSet(candidates=(loaded,))
    assert prepared.profiles["example.cli"] is loaded
    assert prepared.profiles["example.cli"].resources == loaded.resources


@pytest.mark.parametrize("code", list(LOAD_MESSAGES))
def test_load_error_projection_uses_only_a_recognized_code(code: str) -> None:
    class NonRenderingError(ProfileLoadError):
        def __str__(self) -> str:
            raise AssertionError("Raw exception must never be rendered")

        def __repr__(self) -> str:
            raise AssertionError("Raw exception must never be represented")

    error = NonRenderingError(code, field="private-field", line=3, column=7)
    error.args = ("private-args",)
    error.profile_id = "example.cli"
    error.__cause__ = RuntimeError("private-cause")
    error.__context__ = ValueError("private-context")
    prepared = PreparedProfileSet(candidates=[error, candidate()])
    issue = prepared.issues[0]
    assert issue == PreparationIssue(code="LOAD_FAILED", candidate_indices=(0,), load_code=code)
    assert issue.profile_id is None
    assert prepared.lookup("example.cli").status == "PREPARED"
    assert prepared.lookup("example.missing").status == "UNKNOWN"
    error.code = "unknown-after-projection"
    assert issue.load_code == code
    assert "private" not in repr(prepared)
    assert "private" not in issue.message
    for name in ("args", "field", "line", "column", "__cause__", "__context__", "__traceback__"):
        assert not hasattr(issue, name)
    assert {field.name for field in fields(prepared)} == {"_profiles", "_issues", "_rejected"}
    assert all(not isinstance(getattr(issue, field.name), BaseException) for field in fields(issue))


class CodeString(str):
    pass


@pytest.mark.parametrize(
    "code",
    [None, False, 0, [], {}, ("IO_ERROR",), "unknown-secret", CodeString("IO_ERROR"), object()],
)
def test_unknown_or_wrongly_typed_error_codes_are_isolated(code: object) -> None:
    error = ProfileLoadError("IO_ERROR")
    error.code = code
    prepared = PreparedProfileSet(candidates=[error, candidate()])
    assert prepared.issues == (PreparationIssue(code="INVALID_CANDIDATE", candidate_indices=(0,)),)
    assert prepared.lookup("example.cli").status == "PREPARED"
    assert "unknown-secret" not in repr(prepared)


def test_missing_error_code_and_raw_claims_cannot_poison_a_profile_id() -> None:
    loaded = candidate()
    error = ProfileLoadError("IO_ERROR")
    del error.code
    error.profile_id = loaded.definition.profile_id
    raw_claim = SimpleNamespace(definition=loaded.definition, resources=loaded.resources)
    prepared = PreparedProfileSet(candidates=[error, raw_claim, object(), loaded])
    assert [issue.candidate_indices for issue in prepared.issues] == [(0,), (1,), (2,)]
    assert all(issue.code == "INVALID_CANDIDATE" for issue in prepared.issues)
    assert all(issue.profile_id is None for issue in prepared.issues)
    assert prepared.lookup("example.cli").status == "PREPARED"


def test_error_code_projection_never_hashes_compares_or_renders_a_string_subclass() -> None:
    class HostileCode(str):
        __hash__ = None

        def __eq__(self, other: object) -> bool:
            raise AssertionError("An untrusted code must not be compared")

        def __str__(self) -> str:
            raise AssertionError("An untrusted code must not be rendered")

    error = ProfileLoadError("IO_ERROR")
    error.code = HostileCode("IO_ERROR")
    prepared = PreparedProfileSet(candidates=[error, candidate()])
    assert prepared.issues == (PreparationIssue(code="INVALID_CANDIDATE", candidate_indices=(0,)),)
    assert prepared.lookup("example.cli").status == "PREPARED"


@pytest.mark.parametrize("resources", [None, [], {"parser.data": "not bytes"}, {0: b"bytes"}])
def test_malformed_loaded_resource_boundaries_do_not_establish_a_conflicting_id(
    resources: object,
) -> None:
    malformed = object.__new__(LoadedProfile)
    object.__setattr__(malformed, "definition", candidate().definition)
    object.__setattr__(malformed, "resources", resources)
    prepared = PreparedProfileSet(candidates=[malformed, candidate()])
    assert prepared.issues == (PreparationIssue(code="INVALID_CANDIDATE", candidate_indices=(0,)),)
    assert prepared.lookup("example.cli").status == "PREPARED"


@pytest.mark.parametrize("definition", [None, {}, "example.cli", object()])
def test_malformed_loaded_boundaries_have_no_trusted_identity(definition: object) -> None:
    malformed = object.__new__(LoadedProfile)
    object.__setattr__(malformed, "definition", definition)
    prepared = PreparedProfileSet(candidates=[malformed, candidate()])
    assert prepared.issues == (PreparationIssue(code="INVALID_CANDIDATE", candidate_indices=(0,)),)
    assert prepared.lookup("example.cli").status == "PREPARED"


def test_uninitialized_loaded_candidate_is_an_isolated_failure() -> None:
    prepared = PreparedProfileSet(candidates=[object.__new__(LoadedProfile), candidate()])
    assert prepared.issues[0].code == "INVALID_CANDIDATE"
    assert prepared.lookup("example.cli").status == "PREPARED"


def test_preparation_does_not_read_paths_run_commands_or_open_network_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = candidate()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Preparation must be pure")

    with monkeypatch.context() as patch:
        for owner, names in (
            (builtins, ("open",)),
            (io, ("open",)),
            (os, ("open", "read", "stat", "lstat", "system")),
            (Path, ("open", "read_bytes", "read_text", "resolve", "stat")),
            (socket, ("socket", "create_connection", "getaddrinfo")),
            (subprocess, ("run", "Popen")),
        ):
            for name in names:
                patch.setattr(owner, name, forbidden)
        prepared = PreparedProfileSet(candidates=[loaded])
        lookup = prepared.lookup("example.cli")
    assert lookup.profile is loaded
    assert prepared.issues == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"code": "secret", "candidate_indices": (0,)},
        {"code": [], "candidate_indices": (0,)},
        {"code": "INVALID_CANDIDATE", "candidate_indices": ()},
        {"code": "INVALID_CANDIDATE", "candidate_indices": (True,)},
        {"code": "INVALID_CANDIDATE", "candidate_indices": (-1,)},
        {"code": "INVALID_CANDIDATE", "candidate_indices": ("secret",)},
        {"code": "INVALID_CANDIDATE", "candidate_indices": "secret"},
        {"code": "INVALID_CANDIDATE", "candidate_indices": None},
        {"code": "INVALID_CANDIDATE", "candidate_indices": (0, 1)},
        {"code": "DUPLICATE_PROFILE_ID", "candidate_indices": (1, 0), "profile_id": "example"},
        {"code": "DUPLICATE_PROFILE_ID", "candidate_indices": (0, 0), "profile_id": "example"},
        {"code": "DUPLICATE_PROFILE_ID", "candidate_indices": (0,), "profile_id": "example"},
        {"code": "DUPLICATE_PROFILE_ID", "candidate_indices": (0, 1)},
        {"code": "INVALID_REFERENCE", "candidate_indices": (0,)},
        {"code": "RESOURCE_MISSING", "candidate_indices": (0,)},
        {"code": "INVALID_CANDIDATE", "candidate_indices": (0,), "profile_id": "secret-invalid"},
        {"code": "INVALID_CANDIDATE", "candidate_indices": (0,), "load_code": "IO_ERROR"},
        {"code": "LOAD_FAILED", "candidate_indices": (0,)},
        {"code": "LOAD_FAILED", "candidate_indices": (0,), "load_code": []},
        {"code": "LOAD_FAILED", "candidate_indices": (0,), "load_code": "secret"},
        {
            "code": "LOAD_FAILED",
            "candidate_indices": (0,),
            "load_code": "IO_ERROR",
            "profile_id": "example",
        },
    ],
)
def test_issue_validation_is_strict_and_sanitized(kwargs: dict[str, object]) -> None:
    with pytest.raises(NipStackCoreUsageError) as caught:
        PreparationIssue(**kwargs)
    assert "secret" not in str(caught.value)


def test_issue_storage_is_owned_frozen_slotted_and_safely_displayed() -> None:
    indices = [0, 2]
    issue = PreparationIssue(
        code="DUPLICATE_PROFILE_ID", candidate_indices=indices, profile_id="private.profile"
    )
    indices.append(3)
    assert issue.candidate_indices == (0, 2)
    assert not hasattr(issue, "__dict__")
    assert "private.profile" not in repr(issue)
    assert "private.profile" not in issue.message
    with pytest.raises(FrozenInstanceError):
        issue.code = "INVALID_CANDIDATE"
    with pytest.raises(TypeError):
        hash(issue)
