import builtins
import json
import re
import socket
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from nipstack_core.parsers.native.compiler import compile_native
from nipstack_core.parsers.native.model import NativeError, NativeLimits
from nipstack_core.parsers.native.runtime import parse_native
from nipstack_core.parsers.template_resource import extract_template_body

CORPUS = Path(__file__).parents[1] / "profiles/cisco/nxos/cli"


def prepare(body, **limits):
    return compile_native(body.encode(), limits=replace(NativeLimits(), **limits))


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [plain(child) for child in value]
    return value


@pytest.mark.parametrize("case", ["p0-01-n9k-software", "p0-02-n7k-software"])
def test_p0_oracle(case):
    directory = CORPUS / "show_version" / case
    template = compile_native(
        extract_template_body((directory / "template.native").read_bytes(), max_bytes=4096)
    )
    actual = plain(parse_native(template, (directory / "input.txt").read_text()))
    expected = json.loads((directory / "expected.json").read_text())
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


@pytest.mark.parametrize("annotation", ["", " [build LAB]"])
def test_annotation_optional(annotation):
    compiled = prepare(
        "@section\nSoftware\n"
        '  NXOS: version {{ version | required }} {{ ignore | regex="\\[build LAB\\]" | optional }}\n@end'
    )
    assert parse_native(compiled, "Software\n  NXOS: version 10.2(1)" + annotation) == {
        "version": "10.2(1)"
    }


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("", "MISSING_SECTION"),
        ("Hardware\n  NXOS: version 1\n", "MISSING_SECTION"),
        ("Software\n  BIOS: version 1\n", "MISSING_REQUIRED"),
        ("Software\nHardware\n  NXOS: version 1\n", "MISSING_REQUIRED"),
        ("Software\n  NXOS: version\n", "MALFORMED_LINE"),
        ("Software\n  NXOS: version 1 unknown\n", "MALFORMED_LINE"),
        ("Software\n  NXOS: version 1 [build OTHER]\n", "MALFORMED_LINE"),
        ("Software\n  NXOS: version 1 [build LAB] [build LAB]\n", "MALFORMED_LINE"),
        ("Software\n  NXOS: version 1\n  NXOS: version 1\n", "DUPLICATE_CAPTURE"),
        ("Software\n  NXOS: version 1\nSoftware\n  NXOS: version 2\n", "DUPLICATE_SECTION"),
        ("Software\n   NXOS: version 1\n", "INVALID_INDENTATION"),
    ],
)
def test_p0_negative(text, code):
    template = compile_native(
        extract_template_body(
            (CORPUS / "show_version/p0-01-n9k-software/template.native").read_bytes(),
            max_bytes=4096,
        )
    )
    with pytest.raises(NativeError) as caught:
        parse_native(template, text)
    assert caught.value.code == code


def test_unrecognized_does_not_target_by_first_word():
    template = prepare("@section\nSoftware\n  NXOS: version {{ version | required }}\n@end")
    assert parse_native(template, "Software\n  NXOS: broken\n  NXOS: version 1\n") == {
        "version": "1"
    }


@pytest.mark.parametrize("unrelated", ["NXOS: versionX value", "NXOS: versions value"])
def test_complete_literal_words_not_prefixes(unrelated):
    template = prepare("@section\nSoftware\n  NXOS: version {{ version | required }}\n@end")
    assert parse_native(template, f"Software\n  {unrelated}\n  NXOS: version 1") == {"version": "1"}


def test_unrelated_header_word_extension_is_not_malformed():
    template = prepare("@record\nitem {{ id }}\n@end")
    assert parse_native(template, "itemized unrelated") == ()


def test_missing_intermediate_capture_with_complete_literal_words_is_malformed():
    template = prepare("@section\nRoot\n  route {{ first }} via {{ second }}\n@end")
    with pytest.raises(NativeError) as caught:
        parse_native(template, "Root\n  route via target")
    assert caught.value.code == "MALFORMED_LINE"


def test_no_io_or_python_regex_during_compilation_and_parsing(monkeypatch):
    def prohibited(*args, **kwargs):
        raise AssertionError("Unexpected I/O or Python regex")

    monkeypatch.setattr(builtins, "open", prohibited)
    monkeypatch.setattr(socket, "socket", prohibited)
    for name in ("compile", "match", "fullmatch", "search"):
        monkeypatch.setattr(re, name, prohibited)
    template = prepare('@section\nRoot\n  data {{ value | regex="(?:LAB|TEST) [0-9]+" }}\n@end')
    assert parse_native(template, "Root\n  data LAB 42") == {"value": "LAB 42"}


def test_p1_oracle_and_independent_templates():
    directory = CORPUS / "interfaces/p1-04-ethernet-port-channel-boundary"
    body = extract_template_body((directory / "template.native").read_bytes(), max_bytes=4096)
    ethernet = compile_native(body)
    port_channel = compile_native(body.replace(b"Ethernet[0-9]+/[0-9]+", b"port-channel[0-9]+"))
    text = (directory / "input.txt").read_text()
    expected = json.loads((directory / "expected.json").read_text())
    for _ in range(3):
        assert json.dumps(plain(parse_native(ethernet, text)), sort_keys=True) == json.dumps(
            expected, sort_keys=True
        )
        assert plain(parse_native(port_channel, text)) == [
            {"interface": "port-channel10", "description": "LAB_B"}
        ]


def test_record_empty_single_header_only_and_repeated_identical_records():
    template = prepare("@record\nitem {{ id }}\n  value {{ value }}\n@end")
    assert parse_native(template, "") == ()
    assert plain(parse_native(template, "unrelated\n  value skipped\nitem A")) == [{"id": "A"}]
    assert plain(parse_native(template, "item A\n\nitem A\n")) == [{"id": "A"}, {"id": "A"}]


@pytest.mark.parametrize(
    "text",
    [
        "unrecognized source text\n",
        "interface port-channel10\n",
        "interface port-channel10\n  description\n",
    ],
)
def test_record_nonempty_input_without_selected_headers_returns_empty_array(text):
    template = prepare(
        '@record\ninterface {{ interface | regex="Ethernet[0-9]+/[0-9]+" }}\n'
        "  description {{ description | phrase | required }}\n@end"
    )
    result = parse_native(template, text)
    assert result == ()
    assert plain(result) == []


def test_foreign_boundary_resets_optional_fields():
    template = prepare('@record\nitem {{ id | regex="A|B" }}\n  value {{ value | phrase }}\n@end')
    assert plain(parse_native(template, "item A\nforeign\n  value bad\nitem B\n")) == [
        {"id": "A"},
        {"id": "B"},
    ]


def test_record_validation_occurs_at_foreign_boundary():
    template = prepare("@record\nitem {{ id }}\n  value {{ value | required }}\n@end")
    with pytest.raises(NativeError) as caught:
        parse_native(template, "item A\nforeign\n  value too-late\n")
    assert caught.value.code == "MISSING_REQUIRED"


@pytest.mark.parametrize("line_order", [False, True])
@pytest.mark.parametrize("pattern_order", [False, True])
def test_field_and_pattern_order_are_independent(line_order, pattern_order):
    patterns = [
        "  switchport mode {{ mode }}",
        "  switchport access vlan {{ vlan }}",
        "  switchport trunk allowed vlan {{ allowed }}",
    ]
    lines = [
        "  switchport mode trunk",
        "  switchport access vlan 42",
        "  switchport trunk allowed vlan 1,42",
    ]
    if pattern_order:
        patterns.reverse()
    if line_order:
        lines.reverse()
    template = prepare("@section\nRoot\n" + "\n".join(patterns) + "\n@end")
    assert parse_native(template, "Root\n" + "\n".join(lines)) == {
        "mode": "trunk",
        "vlan": "42",
        "allowed": "1,42",
    }


@pytest.mark.parametrize(
    ("modifier", "present", "missing", "valid_missing"),
    [
        ("", "value", "", False),
        (" | phrase", "many words  ", "", False),
        (' | regex="\\[build LAB\\]"', "[build LAB]", "", False),
        (" | optional", "value", "", True),
        (" | phrase | optional", "many words  ", "", True),
        (' | regex="\\[build LAB\\]" | optional', "[build LAB]", "", True),
    ],
)
def test_all_six_ignore_variants(modifier, present, missing, valid_missing):
    template = prepare(f"@section\nRoot\n  field {{{{ value }}}} {{{{ ignore{modifier} }}}}\n@end")
    assert parse_native(template, "Root\n  field kept " + present) == {"value": "kept"}
    text = "Root\n  field kept" + missing
    if valid_missing:
        assert parse_native(template, text) == {"value": "kept"}
    else:
        with pytest.raises(NativeError) as caught:
            parse_native(template, text)
        assert caught.value.code == "MALFORMED_LINE"


def test_ignored_token_segments_and_slots():
    template = prepare("@section\nRoot\n  field {{ ignore }} {{ keep }} {{ ignore }}\n@end")
    assert parse_native(template, "Root\n  field first middle last") == {"keep": "middle"}
    with pytest.raises(NativeError) as caught:
        parse_native(template, "Root\n  field first middle last\n  field first middle last")
    assert caught.value.code == "DUPLICATE_CAPTURE"


@pytest.mark.parametrize("mode", ["phrase", 'regex=".*"'])
def test_absent_and_present_empty_are_distinct(mode):
    template = prepare(f"@section\nRoot\n  value {{{{ value | {mode} | optional }}}}\n@end")
    assert parse_native(template, "Root\n  value") == {}
    assert parse_native(template, "Root\n  value ") == {"value": ""}
    assert parse_native(template, "Root\n  value  ") == {"value": " "}
    assert parse_native(template, "Root\n  value\t  text  ") == {"value": "  text  "}


@pytest.mark.parametrize("ignored", [False, True])
def test_overlap_never_uses_pattern_priority(ignored):
    name = "ignore" if ignored else "second"
    template = prepare(f"@section\nRoot\n  field {{{{ first }}}}\n  field {{{{ {name} }}}}\n@end")
    with pytest.raises(NativeError) as caught:
        parse_native(template, "Root\n  field x")
    assert caught.value.code == "AMBIGUOUS_MATCH"


def test_constraints_can_disambiguate_complete_patterns():
    template = prepare(
        '@section\nRoot\n  field {{ a | regex="[A-Z]+" }}\n  field {{ b | regex="[0-9]+" }}\n@end'
    )
    assert parse_native(template, "Root\n  field LAB\n  field 42") == {"a": "LAB", "b": "42"}
    with pytest.raises(NativeError) as caught:
        parse_native(template, "Root\n  field !")
    assert caught.value.code == "AMBIGUOUS_MATCH"


def test_duplicate_named_scalar_across_patterns():
    template = prepare("@section\nRoot\n  first {{ value }}\n  second {{ value }}\n@end")
    with pytest.raises(NativeError) as caught:
        parse_native(template, "Root\n  first same\n  second same")
    assert caught.value.code == "DUPLICATE_CAPTURE"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_unicode_tabs_and_line_endings(newline):
    template = prepare("@section\nRoot\n\tvalue {{ text | phrase }}\n@end")
    text = newline.join(["Root", "\tvalue \u03a9 caf\u00e9  ", "End", ""])
    result = parse_native(template, text)
    assert result == {"text": "\u03a9 caf\u00e9  "}
    with pytest.raises(TypeError):
        result["text"] = "mutated"


@pytest.mark.parametrize("text", ["Root\n  value \ud800", "\ufeffRoot", "Root\r  value x"])
def test_input_encoding_errors(text):
    template = prepare("@section\nRoot\n  value {{ x }}\n@end")
    with pytest.raises(NativeError) as caught:
        parse_native(template, text)
    assert caught.value.code == "INVALID_ENCODING"
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "name",
    ["max_input_bytes", "max_lines", "max_line_characters", "max_records", "max_output_bytes"],
)
def test_runtime_limits(name):
    limit = {"max_lines": 3, "max_line_characters": 13}.get(name, 1)
    template = prepare("@record\nitem {{ id }}\n@end", **{name: limit})
    text = "item A\nitem B\nitem C\nitem D"
    if name == "max_line_characters":
        text = "item " + "x" * 20
    with pytest.raises(NativeError) as caught:
        parse_native(template, text)
    assert caught.value.code == "RESOURCE_LIMIT"


def test_exact_utf8_input_and_output_thresholds():
    body = "@record\nitem {{ id }}\n@end"
    text = "item \u03a9\nitem \u03bb"
    size = len(
        json.dumps(
            [{"id": "\u03a9"}, {"id": "\u03bb"}], ensure_ascii=False, separators=(",", ":")
        ).encode()
    )
    template = prepare(body, max_input_bytes=len(text.encode()), max_output_bytes=size)
    assert plain(parse_native(template, text)) == [{"id": "\u03a9"}, {"id": "\u03bb"}]
    for argument, value in (
        ("max_input_bytes", len(text.encode()) - 1),
        ("max_output_bytes", size - 1),
    ):
        with pytest.raises(NativeError) as caught:
            parse_native(prepare(body, **{argument: value}), text)
        assert caught.value.code == "RESOURCE_LIMIT"


def test_ignored_values_still_consume_input_budget():
    template = prepare("@section\nRoot\n  secret {{ ignore | phrase }}\n@end", max_input_bytes=32)
    with pytest.raises(NativeError) as caught:
        parse_native(template, "Root\n  secret " + "x" * 100)
    assert caught.value.code == "RESOURCE_LIMIT"


def test_runtime_errors_do_not_interpolate_input(capfd):
    secret = "PRIVATE_PAYLOAD"
    template = prepare('@section\nRoot\n  secret {{ ignore | regex="[0-9]+" }}\n@end')
    with pytest.raises(NativeError) as caught:
        parse_native(template, "Root\n  secret " + secret)
    assert secret not in repr(caught.value)
    assert secret not in repr(template)
    assert caught.value.__context__ is None
    assert capfd.readouterr().err == ""


@pytest.mark.parametrize(
    ("expression", "text"),
    [
        (r"(?:Ethernet|PortChannel)[0-9]+", "PortChannel10"),
        (r"[A-Z][A-Z0-9_]{1,12}", "LAB_A"),
        (r"(?:ab){2,4}", "ababab"),
        (r"\p{Greek}+", "\u03a9\u03bb"),
        (r"\[build LAB\]", "[build LAB]"),
        (r"a|b", "b"),
        (r"\{\{ value \}\}", "{{ value }}"),
        (r"quoted\"value", 'quoted"value'),
        (r"path\\value", "path\\value"),
    ],
)
def test_real_re2_features_and_native_quoting(expression, text):
    compiled = prepare(f'@section\nRoot\n  value {{{{ text | regex="{expression}" }}}}\n@end')
    assert parse_native(compiled, "Root\n  value " + text) == {"text": text}


def test_re2_safe_repetition_on_long_nonmatching_input():
    compiled = prepare(
        '@section\nRoot\n  value {{ text | regex="(a+)+" }}\n@end',
        max_line_characters=16_384,
    )
    with pytest.raises(NativeError) as caught:
        parse_native(compiled, "Root\n  value " + "a" * 10_000 + "b")
    assert caught.value.code == "MALFORMED_LINE"


def test_exact_output_budget_includes_json_escaping_and_optional_empty():
    body = "@section\nRoot\n  value {{ text | phrase }}\n@end"
    value = 'quote" backslash\\ \u03a9\t'
    size = len(json.dumps({"text": value}, ensure_ascii=False, separators=(",", ":")).encode())
    assert parse_native(prepare(body, max_output_bytes=size), "Root\n  value " + value) == {
        "text": value
    }
    with pytest.raises(NativeError) as caught:
        parse_native(prepare(body, max_output_bytes=size - 1), "Root\n  value " + value)
    assert caught.value.code == "RESOURCE_LIMIT"
