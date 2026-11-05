"""Restricted YAML events, exact scalar policy and bounded primitive construction."""

import subprocess
import sys
import traceback
from dataclasses import replace

import pytest
import yaml

from nipstack_core.profiles._yaml import _decode_manifest_yaml
from nipstack_core.profiles.loader import LoadLimits, ProfileLoadError


def decode(text: str, **budgets: int) -> dict:
    return _decode_manifest_yaml(text.encode("utf-8"), limits=LoadLimits(**budgets))


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("null", None),
        ("true", True),
        ("false", False),
        ("0", 0),
        ("-0", 0),
        ("123", 123),
        ("-123", -123),
        ("1.25", 1.25),
        ("1e3", 1000.0),
        ("-2.5e-2", -0.025),
        ("yes", "yes"),
        ("on", "on"),
        ("True", "True"),
        ("FALSE", "FALSE"),
        ("2026-11-05", "2026-11-05"),
        ("0x10", "0x10"),
        ("012", "012"),
        ("+1", "+1"),
        ("1_000", "1_000"),
        ("1:20", "1:20"),
        ("~", "~"),
        ('"true"', "true"),
        ("'null'", "null"),
        ('""', ""),
        ('"é😀"', "é😀"),
        ('"line\\nbreak"', "line\nbreak"),
        ('".nan"', ".nan"),
    ],
)
def test_scalar_policy_has_no_yaml_11_coercions(spelling: str, expected: object) -> None:
    value = decode(f"value: {spelling}\n")["value"]
    assert value == expected
    assert type(value) is type(expected)


def test_nested_primitives_order_and_quoted_merge_like_data() -> None:
    value = decode('first: [a, {nested: [1, null, false]}]\nsecond: {"<<": "data"}\n')
    assert list(value) == ["first", "second"]
    assert value == {"first": ["a", {"nested": [1, None, False]}], "second": {"<<": "data"}}
    assert decode("text: |-\n  first\n  second\n")["text"] == "first\nsecond"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "# comment\n",
        "---\n",
        "scalar",
        "[]",
        "null",
        "a: 1\n---\nb: 2\n",
        "---\na: 1\n---\n",
        "a: [unterminated\n",
        "a: {x: 1\n",
        "a: 1\na: 2\n",
        "a: {nested: 1, nested: 2}",
        'a: {"x": 1, "\\x78": 2}',
        "a: [{x: 1, x: 2}]",
        "a: &unused 1",
        "a: &seq [1]",
        "a: &map {x: 1}",
        "a: *missing",
        "a: &base {x: 1}\nb: {<<: *base}",
        "a: {<<: {x: 1}}",
        "a: !!str value",
        "a: !!int 1",
        "a: !!map {}",
        "a: !custom value",
        "a: !!python/object:example.Synthetic {}",
        "a: !!set {x: null}",
        "%YAML 1.2\n---\na: 1",
        "%YAML 1.1\n---\na: 1",
        "%TAG !e! tag:example.invalid,2026:\n---\na: 1",
        "%UNKNOWN ignored\n---\na: 1",
        "a:",
        "{a}",
        "a: .nan",
        "a: -.Inf",
        "a: +.NAN",
        "a: 1e9999",
        "a: [null, ]\nb:",
        "true: value",
        "1: value",
        "? [a, b]\n: value",
        "? {a: b}\n: value",
        'a: "\\ud800"',
        '"\\udfff": x',
        "\ufeff\ufeffa: 1",
    ],
)
def test_forbidden_or_malformed_yaml_fails(text: str) -> None:
    with pytest.raises(ProfileLoadError) as failure:
        decode(text)
    assert failure.value.code == "INVALID_YAML"


@pytest.mark.parametrize("content", [b"\xff", b"\xc0\xaf", b"\xff\xfea\0:\0 \0b\0"])
def test_non_utf8_is_rejected(content: bytes) -> None:
    with pytest.raises(ProfileLoadError) as failure:
        _decode_manifest_yaml(content, limits=LoadLimits())
    assert failure.value.code == "INVALID_ENCODING"


def test_single_utf8_bom_and_single_explicit_document_are_accepted() -> None:
    assert decode("\ufeff---\na: 1\n...\n") == {"a": 1}
    assert decode('x: "first\n%NOT_A_DIRECTIVE\nlast"\n') == {"x": "first %NOT_A_DIRECTIVE last"}


@pytest.mark.parametrize(
    ("budget", "text", "threshold"),
    [
        ("max_manifest_bytes", "x: a", 4),
        ("max_yaml_nodes", "x: [a, b]", 5),
        ("max_yaml_depth", "x: [[a]]", 3),
        ("max_scalar_bytes", 'x: "é😀"', 6),
        ("max_integer_digits", "x: -1234", 4),
    ],
)
@pytest.mark.parametrize("difference", [-1, 0, 1])
def test_exact_budget_boundaries(budget: str, text: str, threshold: int, difference: int) -> None:
    limits = LoadLimits(**{budget: threshold + difference})
    if difference < 0:
        with pytest.raises(ProfileLoadError) as failure:
            _decode_manifest_yaml(text.encode(), limits=limits)
        assert failure.value.code == "RESOURCE_LIMIT"
    else:
        assert _decode_manifest_yaml(text.encode(), limits=limits)


def test_scalar_limit_counts_decoded_bytes_not_escape_spelling() -> None:
    assert decode('x: "\\u00e9"', max_scalar_bytes=2) == {"x": "é"}
    with pytest.raises(ProfileLoadError):
        decode('x: "\\u00e9"', max_scalar_bytes=1)
    assert decode('"é": x', max_scalar_bytes=2) == {"é": "x"}


def test_default_integer_guard_can_be_configured_without_mutating_python() -> None:
    original = sys.get_int_max_str_digits()
    content = ("x: " + "1" * 513).encode()
    with pytest.raises(ProfileLoadError) as failure:
        _decode_manifest_yaml(content, limits=LoadLimits())
    assert failure.value.code == "RESOURCE_LIMIT"
    value = _decode_manifest_yaml(content, limits=LoadLimits(max_integer_digits=513))
    assert value["x"] == int("1" * 513)
    assert sys.get_int_max_str_digits() == original


def test_interpreter_integer_guard_is_not_bypassed() -> None:
    code = """
import sys
from nipstack_core.profiles._yaml import _decode_manifest_yaml
from nipstack_core.profiles.loader import LoadLimits, ProfileLoadError
before = sys.get_int_max_str_digits()
try:
    _decode_manifest_yaml(b'x: ' + b'1' * 700, limits=LoadLimits(max_integer_digits=1000))
except ProfileLoadError as error:
    assert error.code == 'RESOURCE_LIMIT'
else:
    raise AssertionError('Interpreter limit must be respected')
assert sys.get_int_max_str_digits() == before == 640
"""
    subprocess.run(
        [sys.executable, "-I", "-X", "int_max_str_digits=640", "-c", code],
        check=True,
        timeout=30,
    )


def test_deep_input_is_rejected_without_recursive_composition() -> None:
    text = "x: " + "[" * 2000 + "0" + "]" * 2000
    with pytest.raises(ProfileLoadError) as failure:
        decode(text)
    assert failure.value.code == "RESOURCE_LIMIT"


def test_no_yaml_constructors_or_global_resolver_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    before = {key: list(value) for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()}
    parses = 0
    original = yaml.parse

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Only event parsing is permitted")

    def tracked_parse(*args, **kwargs):
        nonlocal parses
        parses += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(yaml, "parse", tracked_parse)
    monkeypatch.setattr(yaml, "scan", forbidden)
    monkeypatch.setattr(yaml, "load", forbidden)
    monkeypatch.setattr(yaml, "safe_load", forbidden)
    monkeypatch.setattr(yaml, "compose", forbidden)
    monkeypatch.setattr(yaml.constructor.BaseConstructor, "construct_object", forbidden)
    assert decode("x: [true, 1, {nested: text}]")
    assert parses == 1
    assert yaml.SafeLoader.yaml_implicit_resolvers == before


@pytest.mark.parametrize(
    "content",
    [
        b"x: [SYNTHETIC_PRIVATE",
        b"x: !!python/object:SYNTHETIC_PRIVATE {}",
        b"x: \0SYNTHETIC_PRIVATE",
        b"x: \xffSYNTHETIC_PRIVATE",
        b"%SYNTHETIC_PRIVATE ignored\n---\nx: 1",
    ],
)
def test_parser_errors_do_not_display_raw_content(
    content: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(ProfileLoadError) as failure:
        _decode_manifest_yaml(content, limits=LoadLimits())
    error = failure.value
    rendered = str(error) + repr(error) + "".join(traceback.format_exception(error)) + caplog.text
    assert "SYNTHETIC_PRIVATE" not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None
    if error.line is not None:
        assert error.line >= 1 and error.column >= 1


def test_decoder_state_is_per_call_after_failure() -> None:
    with pytest.raises(ProfileLoadError):
        decode("a: [1, 2]", max_yaml_nodes=2)
    assert decode("a: [1, 2]") == {"a": [1, 2]}
    limits = LoadLimits()
    assert _decode_manifest_yaml(b"{}", limits=replace(limits, max_yaml_nodes=1)) == {}
