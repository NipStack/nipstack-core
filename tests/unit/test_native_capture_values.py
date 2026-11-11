import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from nipstack_core.parsers.native.compiler import compile_native
from nipstack_core.parsers.native.model import NativeError, NativeLimits
from nipstack_core.parsers.native.runtime import parse_native
from nipstack_core.parsers.template_resource import extract_template_body

CORPUS = Path(__file__).parents[1] / "profiles/cisco/nxos/cli/interfaces"


def parse(modifiers, value, **limits):
    template = compile_native(
        f"@section\nRoot\n  value {{{{ value | {modifiers} }}}}\n@end".encode(),
        limits=replace(NativeLimits(), **limits),
    )
    return parse_native(template, "Root\n  value " + value)["value"]


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [plain(child) for child in value]
    return value


@pytest.mark.parametrize(
    "case",
    ["p1-01-l2-access-trunk", "p1-02-l3-vrf-boundary", "p1-03-port-channel-reference"],
)
def test_p1_typed_oracles(case):
    directory = CORPUS / case
    compiled = compile_native(
        extract_template_body((directory / "template.native").read_bytes(), max_bytes=4096)
    )
    result = plain(parse_native(compiled, (directory / "input.txt").read_text()))
    expected = json.loads((directory / "expected.json").read_text())
    assert json.dumps(result, sort_keys=True) == json.dumps(expected, sort_keys=True)


@pytest.mark.parametrize(
    ("validator", "value"),
    [
        ("IPV4", "192.0.2.1"),
        ("IPV4", "0.0.0.0"),
        ("IPV4", "224.0.0.1"),
        ("IPV6", "2001:0DB8:0000::1"),
        ("IPV6", "::ffff:192.0.2.1"),
        ("PREFIXV4", "192.0.2.1/31"),
        ("PREFIXV4", "192.0.2.1/0"),
        ("PREFIXV4", "192.0.2.1/32"),
        ("PREFIXV6", "2001:0DB8::1/64"),
        ("PREFIXV6", "::1/0"),
        ("PREFIXV6", "::1/128"),
        ("INT", "+00110"),
        ("INT", "-0"),
    ],
)
def test_validators_preserve_original_strings(validator, value):
    assert parse(validator, value) == value


@pytest.mark.parametrize(
    ("validator", "value"),
    [
        ("IPV4", "256.0.2.1"),
        ("IPV4", "192.000.2.1"),
        ("IPV4", "::1"),
        ("IPV4", "192.0.2.1/24"),
        ("IPV6", "192.0.2.1"),
        ("IPV6", "fe80::1%eth0"),
        ("IPV6", "[2001:db8::1]"),
        ("IPV6", "2001::db8::1"),
        ("PREFIXV4", "192.0.2.1"),
        ("PREFIXV4", "192.0.2.1/255.255.255.0"),
        ("PREFIXV4", "192.0.2.1/0.0.0.255"),
        ("PREFIXV4", "192.0.2.1/33"),
        ("PREFIXV4", "192.0.2.1/-1"),
        ("PREFIXV4", "192.0.2.1/+24"),
        ("PREFIXV4", "192.0.2.1/024"),
        ("PREFIXV6", "::1/129"),
        ("PREFIXV6", "fe80::1%eth0/64"),
        ("INT", "1_10"),
        ("INT", "\u0661\u0661\u0660"),
        ("INT", "+-1"),
        ("INT", "--1"),
        ("INT", "1.0"),
    ],
)
def test_invalid_values_fail_explicitly(validator, value):
    with pytest.raises(NativeError) as caught:
        parse(validator, value)
    assert caught.value.code == "MALFORMED_LINE"


@pytest.mark.parametrize(
    ("modifiers", "value", "expected"),
    [
        ("to_int", "+00110", 110),
        ("INT | to_int", "-42", -42),
        ('split(",")', "110,,120,", ("110", "", "120", "")),
        ('split(", ") | map_int', "110, 120", (110, 120)),
        ('split(",") | map_int', "110,120,110", (110, 120, 110)),
        ('split(",") | expand_ranges("-")', "001,002-004,4", ("001", "2", "3", "4", "4")),
        (
            'split(",") | expand_ranges("-") | map_int',
            "100,105,200-210,300",
            (100, 105, *range(200, 211), 300),
        ),
        ('split(",") | expand_ranges("-") | map_int', "5000,0-1,1", (5000, 0, 1, 1)),
        ('split("|")', "a|b", ("a", "b")),
        ('split("}}")', "a}}b", ("a", "b")),
        ('split("\\\\")', "a\\b", ("a", "b")),
        ('split("\\"")', 'a"b', ("a", "b")),
    ],
)
def test_explicit_transformations(modifiers, value, expected):
    if " " in value:
        modifiers = "phrase | " + modifiers
    assert parse(modifiers, value) == expected


@pytest.mark.parametrize(
    ("modifiers", "value"),
    [
        ("phrase | to_int", " 110"),
        ("to_int", "1_10"),
        ("to_int", "\u0661"),
        ('phrase | split(",") | map_int', "110, 120"),
        ('split(",") | map_int', "1,,2"),
        ('split(",") | map_int', "1-3"),
        ('split(",") | expand_ranges("-")', "3-1"),
        ('split(",") | expand_ranges("-")', "-1-2"),
        ('split(",") | expand_ranges("-")', "1--2"),
        ('split(",") | expand_ranges("-")', "1-"),
        ('split(",") | expand_ranges("-")', "1-2-3"),
        ('split(",") | expand_ranges("-")', "a-b"),
    ],
)
def test_conversion_and_range_failures_are_atomic_and_sanitized(modifiers, value, capfd):
    with pytest.raises(NativeError) as caught:
        parse(modifiers, value)
    assert caught.value.code == "MALFORMED_LINE"
    assert caught.value.__context__ is None
    assert value not in str(caught.value)
    assert capfd.readouterr().err == ""


@pytest.mark.parametrize(
    "modifiers",
    [
        "rest",
        "map_int",
        'to_int | split(",")',
        'split(",") | to_int',
        'split(",") | map_int | expand_ranges("-")',
        "to_int | INT",
        "to_int | phrase",
        "IPV4 | to_int",
        "PREFIXV6 | to_int",
        "IPV4 | IPV6",
        'IPV4 | regex=".*"',
        "split()",
        'split("")',
        'split(",",";")',
        "split(',')",
        'split("\\n")',
        'split(",") | expand_ranges("1")',
    ],
)
def test_invalid_modifier_pipelines_rejected_at_compile_time(modifiers):
    with pytest.raises(NativeError):
        compile_native(f"@section\nRoot\n  value {{{{ value | {modifiers} }}}}\n@end".encode())


def test_integer_conversion_threshold_and_no_interpreter_setting_mutation():
    import sys

    before = sys.get_int_max_str_digits()
    assert parse("to_int", "9" * 640) == int("9" * 640)
    assert parse("INT", "9" * 641) == "9" * 641
    with pytest.raises(NativeError) as caught:
        parse("to_int", "9" * 641)
    assert caught.value.code == "RESOURCE_LIMIT"
    assert sys.get_int_max_str_digits() == before


def test_cumulative_array_budget_and_range_preallocation_limits():
    assert parse('split(",") | expand_ranges("-") | map_int', "1-2", max_transformed_items=5) == (
        1,
        2,
    )
    with pytest.raises(NativeError) as caught:
        parse('split(",") | expand_ranges("-") | map_int', "1-2", max_transformed_items=4)
    assert caught.value.code == "RESOURCE_LIMIT"
    for value in ("0-" + "9" * 640, "0-10000"):
        with pytest.raises(NativeError) as caught:
            parse('split(",") | expand_ranges("-")', value)
        assert caught.value.code == "RESOURCE_LIMIT"


def test_array_budget_is_shared_across_records_and_ignored_values():
    template = compile_native(
        b'@record\nitem {{ id }}\n  value {{ ignore | split(",") }}\n@end',
        limits=NativeLimits(max_transformed_items=3),
    )
    with pytest.raises(NativeError) as caught:
        parse_native(template, "item A\n  value 1,2\nitem B\n  value 3,4")
    assert caught.value.code == "RESOURCE_LIMIT"


def test_transformed_output_budget_is_exact():
    data = {"value": (1, 2)}
    size = len(json.dumps(data, separators=(",", ":")).encode())
    assert parse('split(",") | map_int', "1,2", max_output_bytes=size) == (1, 2)
    with pytest.raises(NativeError) as caught:
        parse('split(",") | map_int', "1,2", max_output_bytes=size - 1)
    assert caught.value.code == "RESOURCE_LIMIT"


@pytest.mark.parametrize("value", ["a via b", "\u03a9 peer", "a  "])
def test_middle_phrase_preserves_exact_content(value):
    template = compile_native(
        b"@section\nRoot\n  neighbor {{ description | phrase }} via {{ next_hop | IPV4 }}\n@end"
    )
    if " via " in value:
        with pytest.raises(NativeError) as caught:
            parse_native(template, f"Root\n  neighbor {value} via 192.0.2.1")
        assert caught.value.code == "AMBIGUOUS_MATCH"
    else:
        assert parse_native(template, f"Root\n  neighbor {value} via 192.0.2.1") == {
            "description": value,
            "next_hop": "192.0.2.1",
        }


def test_literal_phrase_delimiters_and_prefix_region():
    template = compile_native(
        b"@section\nRoot\n  via neighbor {{ value | phrase }} [via+] {{ id }}\n@end"
    )
    assert parse_native(template, "Root\n  via neighbor text [via+] A") == {
        "value": "text",
        "id": "A",
    }


@pytest.mark.parametrize(
    "pattern",
    [
        "{{ a | phrase }} {{ b }}",
        "{{ a | phrase }} via {{ b | phrase }}",
        "{{ a | phrase }} via {{ b | optional }}",
        "{{ a | optional }} via {{ b | phrase }}",
    ],
)
def test_unsupported_middle_phrase_compositions(pattern):
    with pytest.raises(NativeError) as caught:
        compile_native(f"@section\nRoot\n  line {pattern}\n@end".encode())
    assert caught.value.code == "UNSUPPORTED_COMPOSITION"


def test_ignored_values_are_validated_and_transformed_before_discard():
    template = compile_native(b"@section\nRoot\n  value {{ ignore | to_int }}\n@end")
    assert parse_native(template, "Root\n  value 110") == {}
    with pytest.raises(NativeError) as caught:
        parse_native(template, "Root\n  value invalid")
    assert caught.value.code == "MALFORMED_LINE"


def test_optional_absent_transformation_is_not_empty_conversion():
    template = compile_native(
        b"@section\nRoot\n  value {{ ignore | phrase | to_int | optional }}\n@end"
    )
    assert parse_native(template, "Root\n  value") == {}
    with pytest.raises(NativeError) as caught:
        parse_native(template, "Root\n  value ")
    assert caught.value.code == "MALFORMED_LINE"
