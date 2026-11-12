import itertools
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from nipstack_core.parsers.native import runtime
from nipstack_core.parsers.native.compiler import compile_native
from nipstack_core.parsers.native.model import NativeError, NativeLimits
from nipstack_core.parsers.native.runtime import parse_native
from nipstack_core.parsers.template_resource import extract_template_body

CORPUS = Path(__file__).parents[1] / "profiles/cisco/nxos/cli/static_routes"
HEADERS = (
    "ip route {{ prefix | PREFIXV4 }} {{ next_hop | IPV4 }}",
    "ip route {{ prefix | PREFIXV4 }} {{ next_hop | IPV4 }} name {{ name }}",
    "ip route {{ prefix | PREFIXV4 }} {{ next_hop | IPV4 }} name {{ name }} tag {{ tag | INT | to_int }}",
    'ip route {{ prefix | PREFIXV4 }} {{ interface | phrase | regex="Null0" }} name {{ name }}',
    "ip route {{ prefix | PREFIXV4 }} {{ interface }} {{ next_hop | IPV4 }} track {{ track | INT | to_int }} name {{ name }}",
)


def template(headers=HEADERS, body="", **limits):
    source = (
        "@record\nvrf context {{ vrf }}\n@record routes\n"
        + "\n".join("  " + header for header in headers)
        + ("\n" + body if body else "")
        + "\n@end\n@end"
    )
    return compile_native(source.encode(), limits=NativeLimits(**limits))


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [plain(child) for child in value]
    return value


@pytest.mark.parametrize("case", ["p2-02-two-vrf-sections", "p2-03-route-form-alternatives"])
def test_proposed_hierarchical_oracles_exactly(case):
    directory = CORPUS / case
    resource = extract_template_body((directory / "template.native").read_bytes(), max_bytes=4096)
    result = plain(parse_native(compile_native(resource), (directory / "input.txt").read_text()))
    proposed = json.loads((directory / "expected.hierarchical.json").read_text())
    assert json.dumps(result, sort_keys=True) == json.dumps(proposed, sort_keys=True)


@pytest.mark.parametrize("headers", tuple(itertools.permutations(HEADERS)))
def test_all_five_alternative_orderings_produce_identical_hierarchical_results(headers):
    compiled = template(headers)
    for directory in sorted(CORPUS.glob("p2-*")):
        expected = json.loads((directory / "expected.hierarchical.json").read_text())
        actual = plain(parse_native(compiled, (directory / "input.txt").read_text()))
        assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


@pytest.mark.parametrize(
    "route",
    [
        "ip route",
        "ip route 203.0.113.0/24",
        "ip route 203.0.113.0/33 192.0.2.1",
        "ip route 203.0.113.0/24 999.0.2.1",
        "ip route 203.0.113.0/24 192.0.2.1 unsupported",
        "ip route 203.0.113.0/24 Null1 name discard",
        "ip route 203.0.113.0/24 192.0.2.1 name backup tag invalid",
        "ip route 203.0.113.0/24 192.0.2.1 tag 120 name backup",
        "ip route 203.0.113.0/24 Ethernet1/9 192.0.2.1 name tracked track 10",
        "ip route 203.0.113.0/24 Ethernet1/9 invalid track 10 name tracked",
    ],
)
def test_recognized_invalid_or_unsupported_route_is_not_silently_discarded(route, capfd):
    with pytest.raises(NativeError) as caught:
        parse_native(template(), "vrf context A\n  " + route)
    assert caught.value.code == "MALFORMED_LINE"
    assert route not in str(caught.value)
    assert caught.value.__context__ is None
    assert capfd.readouterr().err == ""


@pytest.mark.parametrize("headers", [(HEADERS[0],), HEADERS])
def test_closed_child_grammar_is_unchanged_when_an_alternative_is_added(headers):
    with pytest.raises(NativeError) as caught:
        parse_native(template(headers), "vrf context A\n  ip route 203.0.113.0/24 invalid")
    assert caught.value.code == "MALFORMED_LINE"
    assert parse_native(template(headers), "vrf context A\n  ip router unrelated") == (
        {"vrf": "A", "routes": ()},
    )


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "headers",
    [
        ("item {{ value | phrase }}", "item literal {{ value }}"),
        ("item {{ value | phrase }}", "item {{ value }}"),
    ],
)
def test_overlaps_fail_without_priority_even_for_identical_emitted_values(headers, reverse):
    if reverse:
        headers = headers[::-1]
    line = "item literal X" if "literal" in "".join(headers) else "item X"
    with pytest.raises(NativeError) as caught:
        parse_native(template(headers), "vrf context A\n  " + line)
    assert caught.value.code == "AMBIGUOUS_MATCH"


def test_ambiguous_alternatives_do_not_transform_or_consume_item_budgets(monkeypatch):
    calls = []

    def forbidden(*args):
        calls.append(args)
        raise AssertionError("Transformation ran before selection")

    monkeypatch.setattr(runtime, "transform_value", forbidden)
    # Root emission normally calls transformation too; leave its header capture-free.
    source = "@record\nRoot\n@record items\n  item {{ value | phrase | to_int }}\n  item {{ value | INT }}\n@end\n@end"
    compiled = compile_native(source.encode())
    with pytest.raises(NativeError) as caught:
        parse_native(compiled, "Root\n  item 110")
    assert caught.value.code == "AMBIGUOUS_MATCH"
    assert calls == []


def test_transformation_failure_after_unique_selection_never_tries_another_header(monkeypatch):
    calls = []
    original = runtime.transform_value

    def tracked(capture, value, budget):
        calls.append(capture.name)
        return original(capture, value, budget)

    compiled = template(("item {{ value | phrase | to_int }}", "item literal {{ valid | INT }}"))
    monkeypatch.setattr(runtime, "transform_value", tracked)
    with pytest.raises(NativeError) as caught:
        parse_native(compiled, "vrf context A\n  item literal invalid")
    assert caught.value.code == "MALFORMED_LINE"
    assert calls == ["vrf", "value"]


@pytest.mark.parametrize(
    "headers",
    [
        ("item {{ value }}", "item {{ other }}"),
        ("item {{ value | to_int }}", "item {{ value }}"),
        ('item {{ value | regex="A" }}', 'item {{ value | regex="B" }}'),
        ("item {{ value | IPV4 }}", "item {{ value | IPV6 }}"),
    ],
)
def test_trivially_identical_structural_matchers_rejected(headers):
    with pytest.raises(NativeError) as caught:
        template(headers)
    assert caught.value.code == "INVALID_TEMPLATE"


@pytest.mark.parametrize("prefix", ["@or ", "| "])
def test_no_alternative_directive_or_leading_pipe_marker(prefix):
    with pytest.raises(NativeError):
        template((HEADERS[0], prefix + HEADERS[1]))


def test_alternatives_are_consecutive_and_only_in_named_child_records():
    for source in (
        "@record\nroot {{ id }}\nroot other {{ id }}\n@end",
        "@section\nroot\n@section details\n  detail {{ id }}\n  other {{ id }}\n@end\n@end",
        "@record\nroot\n@record items\n  item {{ id }}\n    value {{ value }}\n  other {{ id }}\n@end\n@end",
    ):
        with pytest.raises(NativeError):
            compile_native(source.encode())


def test_alternatives_share_body_requirements_without_leaking_state():
    compiled = template(
        ("item {{ value }}", "other {{ value }}"),
        body="    note {{ note | phrase | required }}",
    )
    assert parse_native(
        compiled, "vrf context A\n  item X\n    note one\n  other Y\n    note two"
    ) == ({"vrf": "A", "routes": ({"value": "X", "note": "one"}, {"value": "Y", "note": "two"})},)
    with pytest.raises(NativeError) as caught:
        parse_native(compiled, "vrf context A\n  item X\n    note one\n  other Y")
    assert caught.value.code == "MISSING_REQUIRED"


def test_closed_group_does_not_inspect_foreign_or_unselected_subtrees():
    compiled = template()
    text = (
        "vrf context A\n  foreign subtree\n    ip route broken\n"
        "  ip route 203.0.113.0/24 192.0.2.1\n"
        "interface X\n  ip route broken\nvrf context B"
    )
    assert parse_native(compiled, text) == (
        {"vrf": "A", "routes": ({"prefix": "203.0.113.0/24", "next_hop": "192.0.2.1"},)},
        {"vrf": "B", "routes": ()},
    )


@pytest.mark.parametrize("limit", ["max_patterns", "max_captures"])
def test_alternative_compilation_budgets_are_global(limit):
    headers = ("item {{ value }}", "other {{ value }}")
    assert template(headers, **{limit: 3})
    with pytest.raises(NativeError) as caught:
        template(headers, **{limit: 2})
    assert caught.value.code == "RESOURCE_LIMIT"


@pytest.mark.parametrize(
    "line", ["ready state extra", "ready\tstate\textra", "ready state ", "ready state\t"]
)
def test_literal_child_record_rejects_undeclared_suffix(line, capfd):
    with pytest.raises(NativeError) as caught:
        parse_native(template(("ready state",)), "vrf context A\n  " + line)
    assert caught.value.code == "MALFORMED_LINE"
    assert caught.value.line == 2
    assert line not in str(caught.value)
    assert caught.value.__context__ is None
    assert capfd.readouterr().err == ""


@pytest.mark.parametrize(
    "line", ["ready other", "ready stateful", "readyX state extra", "ready state.extra", "ready"]
)
def test_literal_child_record_does_not_target_lexical_prefixes(line):
    assert parse_native(template(("ready state",)), "vrf context A\n  " + line) == (
        {"vrf": "A", "routes": ()},
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_longer_literal_alternative_wins_over_shorter_diagnostic(reverse):
    headers = ("ready [state+]", "ready [state+] extra")
    if reverse:
        headers = headers[::-1]
    compiled = template(headers)
    assert parse_native(compiled, "vrf context A\n  ready\t[state+] extra") == (
        {"vrf": "A", "routes": ({},)},
    )
    with pytest.raises(NativeError) as caught:
        parse_native(compiled, "vrf context A\n  ready [state+] extra invalid")
    assert caught.value.code == "MALFORMED_LINE"


def test_literal_header_still_participates_in_ambiguity_and_indentation_checks():
    with pytest.raises(NativeError) as caught:
        parse_native(
            template(("ready state", "ready {{ value | phrase }}")), "vrf context A\n  ready state"
        )
    assert caught.value.code == "AMBIGUOUS_MATCH"
    with pytest.raises(NativeError) as caught:
        parse_native(template(("ready state",)), "vrf context A\n   ready state extra")
    assert caught.value.code == "INVALID_INDENTATION"


def test_literal_diagnostic_does_not_inspect_skipped_or_unselected_subtrees():
    compiled = compile_native(
        b'@record\nroot {{ id | regex="selected" }}\n@record items\n  ready state\n@end\n@end'
    )
    assert parse_native(
        compiled,
        "root excluded\n  ready state extra\nroot selected\n"
        "  foreign\n    ready state extra\n  ready state",
    ) == ({"id": "selected", "items": ({},)},)


def test_literal_suffix_correction_does_not_change_root_or_child_section_selection():
    assert parse_native(compile_native(b"@record\nRoot\n@end"), "Root extra") == ()
    compiled = compile_native(b"@record\nRoot\n@section details\n  ready state\n@end\n@end")
    assert parse_native(compiled, "Root\n  ready state extra") == ({},)
    assert parse_native(compiled, "Root\n  ready state") == ({"details": {}},)
