"""Local Feature grammar and lexical references, without resource validation."""

from dataclasses import replace

import pytest

from nipstack_core import FeatureSelection, NipStackCoreUsageError
from nipstack_core.profiles import FeatureDefinition, ParserDefinition


def feature() -> FeatureDefinition:
    return FeatureDefinition(
        feature_id="check.global.show_version",
        inputs=["show_version"],
        parser=ParserDefinition(engine="native", template="features/version/parser.yaml"),
        schema="features/version/schema.json",
    )


@pytest.mark.parametrize("engine", ["native", "jmespath"])
def test_parser_models_are_only_references_and_do_not_enforce_extensions(engine: str) -> None:
    value = ParserDefinition(engine=engine, template="resources/custom.data")
    assert value.engine == engine
    assert value.template == "resources/custom.data"
    assert not hasattr(value, "compile")
    assert not hasattr(value, "digest")


@pytest.mark.parametrize("engine", ["ttp", "json", "Native", "", None, 1])
def test_unknown_engines_fail_without_fallback(engine: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        ParserDefinition(engine=engine, template="parser.yaml")


@pytest.mark.parametrize(
    "reference",
    ["schema.json", "features/custom/resource.data", "resources/é.json", "resources/a b.json"],
)
def test_resource_references_are_preserved_without_io_or_filename_conventions(
    reference: str,
) -> None:
    assert replace(feature(), schema=reference).schema == reference
    assert ParserDefinition(engine="native", template=reference).template == reference


@pytest.mark.parametrize(
    "reference",
    [
        None,
        True,
        1,
        "",
        "/schema.json",
        "../schema.json",
        "a/../schema.json",
        "./schema.json",
        "a/./schema.json",
        "a//schema.json",
        "a/",
        "C:/schema.json",
        "a\\schema.json",
        "~/schema.json",
        "$HOME/schema.json",
        "https://example.invalid/schema",
        "a?query",
        "a#fragment",
        " a.json",
        "a.json ",
        "a\nb",
        "a\0b",
        "\ud800",
    ],
)
def test_unsafe_resource_syntax_is_rejected_for_schema_and_template(reference: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(feature(), schema=reference)
    with pytest.raises(NipStackCoreUsageError):
        ParserDefinition(engine="native", template=reference)


@pytest.mark.parametrize(
    "identifier",
    ["check.global.show_version", "config.system.hostname", "custom.network.ipv6", "a.b.c"],
)
def test_feature_ids_use_exactly_the_existing_selection_grammar(identifier: str) -> None:
    assert (
        replace(feature(), feature_id=identifier).feature_id
        == FeatureSelection.features(identifier).values[0]
    )


@pytest.mark.parametrize(
    "identifier",
    [None, 1, "", "a", "a.b", "a.b.c.d", "a..c", "A.b.c", "1a.b.c", "a.b.c-d", "é.b.c"],
)
def test_invalid_feature_ids_fail_at_both_boundaries(identifier: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(feature(), feature_id=identifier)
    with pytest.raises(NipStackCoreUsageError):
        FeatureSelection.features(identifier)


def test_feature_inputs_are_nonempty_owned_ordered_unique_action_ids() -> None:
    inputs = ["first", "second"]
    value = replace(feature(), inputs=inputs)
    inputs.clear()
    assert value.inputs == ("first", "second")
    assert value != replace(value, inputs=["second", "first"])
    another = replace(value, feature_id="custom.global.other")
    assert another.inputs == value.inputs
    assert value.schema == another.schema


@pytest.mark.parametrize(
    "inputs",
    [None, [], (), "action", b"action", {"action"}, iter(["action"]), ["a", "a"], [None], ["a.b"]],
)
def test_invalid_input_structures_fail(inputs: object) -> None:
    with pytest.raises(NipStackCoreUsageError):
        replace(feature(), inputs=inputs)


def test_no_network_commands_inline_resources_or_scope_classification_can_be_added() -> None:
    for keyword in (
        "scope",
        "scope_hint",
        "management_system",
        "managed_system",
        "source_type",
        "command",
        "depends_on",
        "schema_identity",
    ):
        with pytest.raises(TypeError):
            replace(feature(), **{keyword: "not-permitted"})
        assert not hasattr(feature(), keyword)
    with pytest.raises(NipStackCoreUsageError):
        replace(feature(), parser={"engine": "native"})
    with pytest.raises(NipStackCoreUsageError):
        replace(feature(), schema={"type": "object"})
