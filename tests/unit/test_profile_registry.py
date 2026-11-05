"""Immutable preparatory sets, deterministic conflicts and exact lookup."""

from collections import UserList
from collections.abc import Sequence
from dataclasses import FrozenInstanceError, fields, replace
from inspect import Parameter, signature
from itertools import permutations
from types import SimpleNamespace
from typing import get_type_hints

import pytest

import nipstack_core
from nipstack_core import NipStackCoreUsageError, contracts, profiles
from nipstack_core.profiles import (
    ConnectionDefinition,
    FeatureDefinition,
    ParserDefinition,
    ProfileDefinition,
    ProfileMetadata,
)
from nipstack_core.profiles._load_types import LoadedProfile, ProfileLoadError
from nipstack_core.profiles.registry import PreparationInput, PreparationLookup, PreparedProfileSet
from nipstack_core.profiles.validation import PreparationIssue


def candidate(profile_id: str = "example.profile", version: str = "1.0.0") -> LoadedProfile:
    return LoadedProfile(
        definition=ProfileDefinition(
            profile_id=profile_id,
            version=version,
            metadata=ProfileMetadata(
                name="Synthetic", vendor="example", platform_id="example", access_variant="test"
            ),
            connection=ConnectionDefinition(connector="ssh"),
            actions={},
            features={},
        ),
        resources={},
    )


def invalid_candidate(profile_id: str = "example.invalid") -> LoadedProfile:
    loaded = candidate(profile_id)
    feature = FeatureDefinition(
        feature_id="check.global.status",
        inputs=["missing"],
        parser=ParserDefinition(engine="native", template="parser.data"),
        schema="schema.data",
    )
    return replace(
        loaded, definition=replace(loaded.definition, features={feature.feature_id: feature})
    )


@pytest.mark.parametrize("container", [list, tuple])
def test_empty_native_containers_build_empty_preparatory_sets(container: type) -> None:
    prepared = PreparedProfileSet(candidates=container())
    assert dict(prepared.profiles) == {}
    assert prepared.issues == ()
    assert prepared.lookup("example.unknown") == PreparationLookup(status="UNKNOWN")
    assert prepared.deferred_checks


class ListSubclass(list):
    pass


class TupleSubclass(tuple):
    pass


class NonEvaluableSequence(Sequence):
    def __len__(self) -> int:
        raise AssertionError("Unsupported containers must not be evaluated")

    def __getitem__(self, index: object) -> object:
        raise AssertionError("Unsupported containers must not be evaluated")


@pytest.mark.parametrize(
    "value",
    [
        None,
        "secret",
        b"secret",
        bytearray(),
        {},
        set(),
        {0},
        range(2),
        False,
        1,
        iter(()),
        UserList(),
        ListSubclass(),
        TupleSubclass(),
        NonEvaluableSequence(),
    ],
)
def test_global_container_misuse_raises_before_consuming_inputs(value: object) -> None:
    with pytest.raises(NipStackCoreUsageError) as caught:
        PreparedProfileSet(candidates=value)
    assert "secret" not in str(caught.value)


def test_generators_are_rejected_without_iteration() -> None:
    def generated():
        raise AssertionError("Generator must not be evaluated")
        yield candidate()

    generator = generated()
    try:
        with pytest.raises(NipStackCoreUsageError):
            PreparedProfileSet(candidates=generator)
    finally:
        generator.close()


@pytest.mark.parametrize("element", [None, "secret", b"secret", 1, {}, object()])
def test_invalid_elements_are_isolated_inside_a_valid_container(element: object) -> None:
    loaded = candidate()
    prepared = PreparedProfileSet(candidates=[loaded, element])
    assert prepared.profiles["example.profile"] is loaded
    assert prepared.issues == (PreparationIssue(code="INVALID_CANDIDATE", candidate_indices=(1,)),)


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0", "1.0.0-alpha", "1.0.0+build"])
def test_duplicate_ids_have_no_winner_regardless_of_version(version: str) -> None:
    first = candidate()
    second = candidate(version=version)
    prepared = PreparedProfileSet(candidates=[first, second])
    lookup = prepared.lookup("example.profile")
    assert lookup.status == "CONFLICT"
    assert lookup.profile is None
    assert not prepared.profiles
    assert prepared.issues == (
        PreparationIssue(
            code="DUPLICATE_PROFILE_ID", candidate_indices=(0, 1), profile_id="example.profile"
        ),
    )
    assert lookup.issues == prepared.issues


@pytest.mark.parametrize("duplicate_kind", ["same_object", "equal_copy", "different_resources"])
def test_duplicate_occurrences_are_not_deduplicated(duplicate_kind: str) -> None:
    first = candidate()
    second = first if duplicate_kind == "same_object" else replace(first)
    if duplicate_kind == "different_resources":
        second = replace(first, resources={"extra.data": b"different"})
    prepared = PreparedProfileSet(candidates=[first, second, first])
    assert prepared.lookup("example.profile").status == "CONFLICT"
    assert len(prepared.issues) == 1
    assert prepared.issues[0].candidate_indices == (0, 1, 2)


def test_identifiable_invalid_candidate_still_conflicts_and_retains_its_local_issue() -> None:
    valid = candidate()
    invalid = invalid_candidate("example.profile")
    survivor = candidate("example.survivor")
    for inputs in permutations((valid, invalid, survivor)):
        prepared = PreparedProfileSet(candidates=inputs)
        assert list(prepared.profiles) == ["example.survivor"]
        assert prepared.lookup("example.profile").status == "CONFLICT"
        assert prepared.lookup("example.profile").profile is None
        assert [issue.code for issue in prepared.issues] == [
            "INVALID_REFERENCE",
            "DUPLICATE_PROFILE_ID",
        ]
        assert prepared.issues[0].candidate_indices == (inputs.index(invalid),)
        expected = tuple(index for index, value in enumerate(inputs) if value is not survivor)
        assert prepared.issues[1].candidate_indices == expected


def test_two_invalid_candidates_conflict_without_prepared_payload() -> None:
    invalid = invalid_candidate()
    prepared = PreparedProfileSet(candidates=[invalid, invalid])
    assert [issue.code for issue in prepared.issues] == [
        "INVALID_REFERENCE",
        "INVALID_REFERENCE",
        "DUPLICATE_PROFILE_ID",
    ]
    assert prepared.lookup("example.invalid").status == "CONFLICT"
    assert prepared.lookup("example.invalid").profile is None


def test_raw_claims_and_opaque_load_failures_do_not_participate_in_conflicts() -> None:
    loaded = candidate()
    error = ProfileLoadError("INVALID_MANIFEST")
    error.profile_id = "example.profile"
    raw = SimpleNamespace(profile_id="example.profile", version="1.0.0")
    prepared = PreparedProfileSet(candidates=[error, raw, loaded])
    assert prepared.lookup("example.profile").status == "PREPARED"
    assert [issue.code for issue in prepared.issues] == ["LOAD_FAILED", "INVALID_CANDIDATE"]
    assert all(issue.profile_id is None for issue in prepared.issues)


def test_admission_is_permutation_invariant_but_indices_track_each_input_order() -> None:
    values = (candidate("example.b"), candidate("example.a"), candidate("example.b", "2.0.0"))
    for inputs in permutations(values):
        prepared = PreparedProfileSet(candidates=inputs)
        assert list(prepared.profiles) == ["example.a"]
        assert prepared.lookup("example.a").status == "PREPARED"
        assert prepared.lookup("example.b").status == "CONFLICT"
        expected = tuple(
            index
            for index, value in enumerate(inputs)
            if value.definition.profile_id == "example.b"
        )
        assert prepared.issues[0].candidate_indices == expected


def test_issue_order_is_local_input_order_then_conflict_first_occurrence() -> None:
    values = [
        candidate("example.z"),
        invalid_candidate(),
        candidate("example.a"),
        ProfileLoadError("IO_ERROR"),
        candidate("example.a"),
        candidate("example.z"),
        candidate("example.keep"),
        None,
    ]
    prepared = PreparedProfileSet(candidates=values)
    assert [issue.candidate_indices for issue in prepared.issues] == [
        (1,),
        (3,),
        (7,),
        (0, 5),
        (2, 4),
    ]
    assert list(prepared.profiles) == ["example.keep"]
    assert prepared.lookup("example.z").issues == (prepared.issues[3],)
    assert prepared.lookup("example.invalid").issues == (prepared.issues[0],)


def test_lookup_distinguishes_all_four_statuses_and_never_uses_an_operational_enum() -> None:
    prepared = PreparedProfileSet(
        candidates=[
            candidate("example.ok"),
            invalid_candidate(),
            candidate(),
            candidate(),
            ProfileLoadError("IO_ERROR"),
        ]
    )
    for profile_id, status in (
        ("example.ok", "PREPARED"),
        ("example.invalid", "INVALID"),
        ("example.profile", "CONFLICT"),
        ("example.unknown", "UNKNOWN"),
    ):
        lookup = prepared.lookup(profile_id)
        assert lookup.status == status
        assert type(lookup.status) is str
        assert (lookup.profile is not None) == (status == "PREPARED")
        assert bool(lookup.issues) == (status in ("INVALID", "CONFLICT"))
        assert not hasattr(lookup, "deferred_checks")


@pytest.mark.parametrize("query", ["Example.Profile", "x-y", "example..profile", "ex\u00e4mple"])
def test_lookup_uses_exact_opaque_text_without_canonicalizing(query: str) -> None:
    prepared = PreparedProfileSet(candidates=[candidate()])
    assert prepared.lookup(query).status == "UNKNOWN"


@pytest.mark.parametrize(
    "query",
    [
        None,
        False,
        1,
        [],
        {},
        b"example.profile",
        "",
        "  ",
        "x\n",
        " example.profile",
        "example.profile ",
    ],
)
def test_lookup_reuses_public_text_validation_for_invalid_queries(query: object) -> None:
    prepared = PreparedProfileSet(candidates=[])
    with pytest.raises(NipStackCoreUsageError):
        prepared.lookup(query)


def test_input_copy_owned_mappings_and_sorted_profiles_remain_stable() -> None:
    values = [candidate("example.z"), candidate("example.a")]
    prepared = PreparedProfileSet(candidates=values)
    values.clear()
    assert list(prepared.profiles) == ["example.a", "example.z"]
    with pytest.raises(TypeError):
        prepared.profiles["example.injected"] = candidate()
    with pytest.raises(TypeError):
        prepared.profiles["example.a"].resources["injected.data"] = b"data"
    with pytest.raises(FrozenInstanceError):
        prepared._issues = ()
    assert not hasattr(prepared, "__dict__")
    with pytest.raises(TypeError):
        hash(prepared)
    rebuilt = PreparedProfileSet(candidates=[])
    assert rebuilt.profiles == {}
    assert list(prepared.profiles) == ["example.a", "example.z"]


def test_deferred_families_are_fixed_set_wide_facts_not_individual_applicability() -> None:
    expected = (
        "CONNECTOR_CAPABILITIES",
        "PARSER_TEMPLATE_VALIDATION",
        "PARSER_INPUT_COMPATIBILITY",
        "FINGERPRINT_SEMANTICS",
        "OBSERVATION_SCHEMA_VALIDATION",
        "SCHEMA_IDENTITY",
        "ACTIVATION_GATE",
    )
    for values in ([], [candidate()], [invalid_candidate()], [candidate(), candidate()]):
        prepared = PreparedProfileSet(candidates=values)
        assert prepared.deferred_checks == expected
        for value in (prepared, prepared.lookup("example.profile")):
            for attribute in ("active", "validated", "activate", "force_valid", "attest"):
                assert not hasattr(value, attribute)
        with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
            prepared.deferred_checks = ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"profiles": {}},
        {"_profiles": {}},
        {"candidates": [], "issues": ()},
        {"candidates": [], "active": True},
        {"candidates": [], "validated": True},
        {"candidates": [], "deferred_checks": ()},
        {"candidates": [], "_rejected": {}},
    ],
)
def test_only_the_constructor_builder_accepts_preparation_inputs(kwargs: dict[str, object]) -> None:
    with pytest.raises(TypeError):
        PreparedProfileSet(**kwargs)


def test_constructor_is_keyword_only_and_cannot_be_replaced_with_internal_state() -> None:
    assert tuple(signature(PreparedProfileSet).parameters) == ("candidates",)
    assert signature(PreparedProfileSet).parameters["candidates"].kind == Parameter.KEYWORD_ONLY
    assert get_type_hints(PreparedProfileSet.__init__)["candidates"] == (
        list[PreparationInput] | tuple[PreparationInput, ...]
    )
    with pytest.raises(TypeError):
        PreparedProfileSet([])
    with pytest.raises(TypeError):
        replace(PreparedProfileSet(candidates=[]))


@pytest.mark.parametrize(
    "failure", [RuntimeError("unexpected"), KeyboardInterrupt(), SystemExit(), MemoryError()]
)
def test_unexpected_errors_and_interruptions_propagate(
    failure: BaseException, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(value: LoadedProfile) -> None:
        raise failure

    monkeypatch.setattr("nipstack_core.profiles.registry._check_loaded_structure", fail)
    with pytest.raises(type(failure)) as caught:
        PreparedProfileSet(candidates=[candidate()])
    assert caught.value is failure


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "active"},
        {"status": []},
        {"status": "PREPARED"},
        {"status": "INVALID"},
        {"status": "CONFLICT"},
        {"status": "UNKNOWN", "profile": candidate()},
        {"status": "INVALID", "profile": candidate()},
        {"status": "CONFLICT", "profile": candidate()},
        {"status": "PREPARED", "profile": object()},
        {"status": "UNKNOWN", "issues": "raw"},
        {"status": "UNKNOWN", "issues": None},
        {"status": "UNKNOWN", "issues": (object(),)},
        {
            "status": "UNKNOWN",
            "issues": (PreparationIssue(code="INVALID_CANDIDATE", candidate_indices=(0,)),),
        },
        {
            "status": "PREPARED",
            "profile": candidate(),
            "issues": (PreparationIssue(code="INVALID_CANDIDATE", candidate_indices=(0,)),),
        },
        {
            "status": "INVALID",
            "issues": (PreparationIssue(code="INVALID_CANDIDATE", candidate_indices=(0,)),),
        },
        {
            "status": "CONFLICT",
            "issues": (
                PreparationIssue(
                    code="RESOURCE_MISSING", candidate_indices=(0,), profile_id="example"
                ),
            ),
        },
        {
            "status": "INVALID",
            "issues": (
                PreparationIssue(
                    code="DUPLICATE_PROFILE_ID", candidate_indices=(0, 1), profile_id="example"
                ),
            ),
        },
        {
            "status": "INVALID",
            "issues": (
                PreparationIssue(code="RESOURCE_MISSING", candidate_indices=(0,), profile_id="a"),
                PreparationIssue(code="RESOURCE_MISSING", candidate_indices=(1,), profile_id="b"),
            ),
        },
    ],
)
def test_lookup_payload_invariants_are_enforced(kwargs: dict[str, object]) -> None:
    with pytest.raises(NipStackCoreUsageError):
        PreparationLookup(**kwargs)


def test_lookup_owns_issues_and_is_frozen_slotted_unhashable_and_safely_displayed() -> None:
    issue = PreparationIssue(
        code="INVALID_REFERENCE", candidate_indices=(0,), profile_id="private.profile"
    )
    issues = [issue]
    lookup = PreparationLookup(status="INVALID", issues=issues)
    issues.clear()
    assert lookup.issues == (issue,)
    assert "private.profile" not in repr(lookup)
    assert not hasattr(lookup, "__dict__")
    with pytest.raises(FrozenInstanceError):
        lookup.status = "PREPARED"
    with pytest.raises(TypeError):
        hash(lookup)
    assert {field.name for field in fields(lookup)} == {"status", "profile", "issues"}


def test_preparatory_names_do_not_change_any_existing_export_surface() -> None:
    names = {"PreparedProfileSet", "PreparationLookup", "PreparationIssue", "PreparationInput"}
    assert len(nipstack_core.__all__) == len(contracts.__all__) == 33
    for module in (nipstack_core, contracts, profiles):
        assert not names.intersection(module.__all__)
        for name in names | {"ProfileRegistry"}:
            assert not hasattr(module, name)
