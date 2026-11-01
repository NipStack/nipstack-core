"""Offline tests of the public selection and API-misuse contracts."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from enum import Enum
from operator import setitem

import pytest

import nipstack_core
from nipstack_core import FeatureSelection, FeatureSelectionKind, NipStackCoreUsageError, contracts


def test_all_is_explicit_and_has_no_values() -> None:
    selection = FeatureSelection.all()

    assert selection.kind is FeatureSelectionKind.ALL
    assert selection.values == ()
    assert selection == FeatureSelection.all()


def test_selection_kinds_are_a_standard_enum() -> None:
    assert issubclass(FeatureSelectionKind, Enum)
    assert [(kind.name, kind.value) for kind in FeatureSelectionKind] == [
        ("ALL", "all"),
        ("MODES", "modes"),
        ("FEATURES", "features"),
    ]
    assert FeatureSelectionKind.ALL != "all"


@pytest.mark.parametrize("mode", ["a", "check", "config", "custom", "a0", "a_", "a__b"])
def test_modes_accept_valid_identifiers_without_profile_lookup(mode: str) -> None:
    selection = FeatureSelection.modes(mode)

    assert selection.kind is FeatureSelectionKind.MODES
    assert selection.values == (mode,)


@pytest.mark.parametrize(
    "feature",
    [
        "a.b.c",
        "check.global.show_version",
        "config.routing.bgp",
        "custom.network.ipv6",
        "a0.b1.c2",
        "a_.b__.c_d",
    ],
)
def test_features_accept_valid_ids_without_profile_lookup(feature: str) -> None:
    selection = FeatureSelection.features(feature)

    assert selection.kind is FeatureSelectionKind.FEATURES
    assert selection.values == (feature,)


@pytest.mark.parametrize(
    ("factory", "values", "kind", "expected"),
    [
        (
            FeatureSelection.modes,
            ("config", "check", "config", "custom", "check"),
            FeatureSelectionKind.MODES,
            ("config", "check", "custom"),
        ),
        (
            FeatureSelection.features,
            ("config.routing.bgp", "check.global.show_version", "config.routing.bgp"),
            FeatureSelectionKind.FEATURES,
            ("config.routing.bgp", "check.global.show_version"),
        ),
    ],
)
def test_duplicates_preserve_first_appearance(
    factory: Callable[..., FeatureSelection],
    values: tuple[str, ...],
    kind: FeatureSelectionKind,
    expected: tuple[str, ...],
) -> None:
    selection = factory(*values)

    assert selection.kind is kind
    assert selection.values == expected


@pytest.mark.parametrize("factory", [FeatureSelection.modes, FeatureSelection.features])
def test_empty_selection_is_an_error_not_all(factory: Callable[..., FeatureSelection]) -> None:
    with pytest.raises(NipStackCoreUsageError, match="requires at least one identifier"):
        factory()


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "\t",
        "\n",
        "Check",
        "CHECK",
        " check",
        "check ",
        "check\n",
        "ch eck",
        "a.b",
        "a.b.c",
        "a-b",
        "_a",
        "1a",
        "ä",
        "ａ",
    ],
)
def test_modes_reject_malformed_identifiers(value: str) -> None:
    with pytest.raises(NipStackCoreUsageError, match="argument 1"):
        FeatureSelection.modes(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "check",
        "a.b",
        "a..c",
        ".b.c",
        "a.b.",
        "a.b.c.d",
        "A.b.c",
        "a.B.c",
        "a.b.C",
        "1a.b.c",
        "a.1b.c",
        "a.b.1c",
        "_a.b.c",
        "a.b.c-d",
        " a.b.c",
        "a.b.c ",
        "a.b.c\n",
        "a.b.\nc",
        "ä.b.c",
        "a.β.c",
        "a.b.ｃ",
    ],
)
def test_features_reject_malformed_identifiers(value: str) -> None:
    with pytest.raises(NipStackCoreUsageError, match="argument 1"):
        FeatureSelection.features(value)


@pytest.mark.parametrize("factory", [FeatureSelection.modes, FeatureSelection.features])
@pytest.mark.parametrize(
    "value",
    [None, True, False, 0, 1, 1.5, b"check", [], ["check"], (), ("check",), {}, {"check"}],
)
def test_invalid_types_raise_usage_error_without_coercion(
    factory: Callable[..., FeatureSelection], value: object
) -> None:
    with pytest.raises(NipStackCoreUsageError, match="argument 1 must be a string"):
        factory(value)


@pytest.mark.parametrize(
    ("factory", "valid"),
    [
        (FeatureSelection.modes, "check"),
        (FeatureSelection.features, "check.global.show_version"),
    ],
)
def test_invalid_later_values_are_not_hidden_or_echoed(
    factory: Callable[..., FeatureSelection], valid: str
) -> None:
    invalid = "SYNTHETIC_PRIVATE_INPUT"

    with pytest.raises(NipStackCoreUsageError, match="argument 3") as raised:
        factory(valid, valid, invalid)

    assert invalid not in str(raised.value)
    assert valid not in str(raised.value)


def test_invalid_objects_are_not_formatted_in_errors() -> None:
    class Unformattable:
        def __str__(self) -> str:
            raise AssertionError("Input must not be formatted.")

        def __repr__(self) -> str:
            raise AssertionError("Input must not be represented.")

    for factory in (FeatureSelection.modes, FeatureSelection.features):
        with pytest.raises(NipStackCoreUsageError, match="must be a string"):
            factory(Unformattable())


@pytest.mark.parametrize(
    ("args", "kwargs"),
    [
        ((), {}),
        (("check",), {}),
        ((FeatureSelectionKind.ALL, ()), {}),
        ((FeatureSelectionKind.MODES, ("check",)), {}),
        ((), {"kind": FeatureSelectionKind.ALL, "values": ()}),
        ((), {"kind": FeatureSelectionKind.MODES, "values": ("check",)}),
    ],
)
def test_direct_construction_always_raises_type_error(
    args: tuple[object, ...], kwargs: dict[str, object]
) -> None:
    with pytest.raises(TypeError):
        FeatureSelection(*args, **kwargs)


def test_calls_outside_factory_signatures_raise_native_type_error() -> None:
    with pytest.raises(TypeError):
        FeatureSelection.all("check")
    for factory in (FeatureSelection.all, FeatureSelection.modes, FeatureSelection.features):
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            factory(unexpected="check")


@pytest.mark.parametrize(
    "selection",
    [
        FeatureSelection.all(),
        FeatureSelection.modes("check", "config"),
        FeatureSelection.features("check.global.show_version"),
    ],
)
def test_factory_results_are_initialized_and_frozen(selection: FeatureSelection) -> None:
    assert isinstance(selection.kind, FeatureSelectionKind)
    assert isinstance(selection.values, tuple)
    assert not hasattr(selection, "__dict__")
    assert (selection.kind is FeatureSelectionKind.ALL) == (selection.values == ())
    for attribute in ("kind", "values"):
        with pytest.raises(FrozenInstanceError):
            setattr(selection, attribute, None)
        with pytest.raises(FrozenInstanceError):
            delattr(selection, attribute)
    if selection.values:
        with pytest.raises(TypeError):
            setitem(selection.values, 0, "changed")


def test_selection_does_not_retain_mutable_input_containers() -> None:
    values = ["check", "config"]
    selection = FeatureSelection.modes(*values)
    values[0] = "changed"
    values.clear()

    assert selection.values == ("check", "config")


def test_equality_and_hash_use_kind_and_ordered_distinct_values() -> None:
    selection = FeatureSelection.modes("check", "config")
    equivalent = FeatureSelection.modes("check", "config", "check")
    features = FeatureSelection.features("a.b.c", "d.e.f")

    assert selection == equivalent
    assert hash(selection) == hash(equivalent)
    assert {selection: "selected"}[equivalent] == "selected"
    assert selection != FeatureSelection.modes("config", "check")
    assert features != FeatureSelection.features("d.e.f", "a.b.c")
    assert selection != FeatureSelection.all()
    assert selection != features
    assert selection != (FeatureSelectionKind.MODES, ("check", "config"))
    assert len({selection, equivalent, FeatureSelection.all(), features}) == 3


def test_repr_describes_kind_and_values() -> None:
    assert repr(FeatureSelection.modes("check")) == (
        "FeatureSelection(kind=<FeatureSelectionKind.MODES: 'modes'>, values=('check',))"
    )
    assert repr(FeatureSelection.all()) == (
        "FeatureSelection(kind=<FeatureSelectionKind.ALL: 'all'>, values=())"
    )


def test_public_exports_are_real_and_consistent() -> None:
    expected = {
        "BearerTokenAuth",
        "CollectionResult",
        "CollectionStatus",
        "ConnectionTarget",
        "DiagnosticCode",
        "ErrorCode",
        "ErrorStage",
        "ExecutionMetadata",
        "FeatureResult",
        "FeatureSelection",
        "FeatureSelectionKind",
        "FeatureStatus",
        "HTTPEndpoint",
        "JSONDocument",
        "JSONValue",
        "NipStackCoreDiagnostic",
        "NipStackCoreError",
        "NipStackCoreUsageError",
        "NoAuth",
        "ProfileIdentity",
        "RawArtifact",
        "RawArtifactPolicy",
        "RetryHint",
        "SchemaIdentity",
        "ScopeHint",
        "SecretValue",
        "SSHKeyAuth",
        "SSHEndpoint",
        "TargetDescriptor",
        "UsernamePasswordAuth",
    }

    assert set(nipstack_core.__all__) == set(contracts.__all__) == expected
    for name in expected:
        assert getattr(nipstack_core, name) is getattr(contracts, name)
    assert issubclass(NipStackCoreUsageError, ValueError)
    assert not hasattr(nipstack_core, "collect")
