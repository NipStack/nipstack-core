from dataclasses import FrozenInstanceError, replace

import pytest

from nipstack_core.parsers.native.compiler import compile_native
from nipstack_core.parsers.native.model import NativeError, NativeLimits


def test_immutable_compilation():
    compiled = compile_native(b"@record\nitem {{ id }}\n  value {{ text | rest }}\n@end\n")
    assert compiled.kind == "record"
    assert isinstance(compiled.body, tuple)
    with pytest.raises(FrozenInstanceError):
        compiled.kind = "section"
    with pytest.raises(FrozenInstanceError):
        compiled.header.captures[0].optional = True


@pytest.mark.parametrize("kind", ["section", "record"])
@pytest.mark.parametrize("name", ["interface", "ignore"])
@pytest.mark.parametrize("capture_type", ["", " | rest", ' | regex="[A-Z]+"'])
@pytest.mark.parametrize("modifier", ["optional", "required"])
def test_header_captures_reject_presence_modifiers(kind, name, capture_type, modifier):
    with pytest.raises(NativeError) as caught:
        compile_native(
            f"@{kind}\ninterface {{{{ {name}{capture_type} | {modifier} }}}}\n@end".encode()
        )
    assert caught.value.code == "INVALID_TEMPLATE"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "@section\n@end",
        "@section\nRoot",
        "@end",
        "@group\nRoot\n@end",
        "@native 40b-1\n@section\nRoot\n@end",
        "@section\nRoot\n@record\nx\n@end\n@end",
        "@section\nRoot\n@end\n@section\nOther\n@end",
        "@section\n Root\n@end",
        "@section\nRoot\nfield {{ a }}\n@end",
        "@section\nRoot\n  a {{ x }}\n   b {{ y }}\n@end",
        "@section\nRoot\n  x {{ x | optional | required }}\n@end",
        "@section\nRoot\n  x {{ x | prefix=E }}\n@end",
        '@section\nRoot\n  x {{ x | rest | regex=".*" }}\n@end',
        "@section\nRoot\n  x {{ x | required | required }}\n@end",
        "@section\nRoot\n  x {{ a }} {{ a }}\n@end",
        "@section\nRoot\n  x {{ 1name }}\n@end",
        "@section\nRoot\n  x {{ x\n@end",
        '@section\nRoot\n  x {{ x | regex="unterminated }}\n@end',
        "@section\nRoot\n  literal-only\n@end",
        "<template>\n@section\nRoot\n@end\n</template>",
    ],
)
def test_invalid_templates(body):
    with pytest.raises(NativeError):
        compile_native(body.encode())


@pytest.mark.parametrize(
    "pattern",
    [
        "{{ a }}{{ b }}",
        "{{ a }}-{{ b }}",
        "{{ a | rest }} suffix",
        '{{ a | regex=".*" }} {{ b }}',
        "{{ a | optional }} {{ b }}",
        "{{ a | optional }}",
        "prefix{{ a }}",
    ],
)
def test_unsupported_compositions(pattern):
    with pytest.raises(NativeError) as caught:
        compile_native(f"@section\nRoot\n  {pattern}\n@end".encode())
    assert caught.value.code == "UNSUPPORTED_COMPOSITION"


@pytest.mark.parametrize("expression", [r"(x)\1", r"x(?=y)", r"x(?!y)", r"x++", r"[", r"x{1001}"])
def test_regex_failures_are_sanitized(expression, capfd):
    with pytest.raises(NativeError) as caught:
        compile_native(
            f'@section\nRoot\n  field {{{{ value | regex="{expression}" }}}}\n@end'.encode()
        )
    assert caught.value.code == "INVALID_REGEX"
    assert caught.value.__context__ is None
    assert expression not in str(caught.value)
    assert capfd.readouterr().err == ""


@pytest.mark.parametrize(
    "body", [b"\xff", b"\xef\xbb\xbf@section\nRoot\n@end", b"@section\rRoot\r@end"]
)
def test_invalid_encoding(body):
    with pytest.raises(NativeError) as caught:
        compile_native(body)
    assert caught.value.code == "INVALID_ENCODING"
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "limits",
    [
        {"max_template_bytes": 1},
        {"max_lines": 2},
        {"max_line_characters": 3},
        {"max_patterns": 1},
        {"max_captures": 1},
        {"max_regex_bytes": 1},
    ],
)
def test_compile_limits(limits):
    body = b'@record\nitem {{ id }}\n  field {{ value | regex="[a-z]+" }}\n@end'
    with pytest.raises(NativeError) as caught:
        compile_native(body, limits=replace(NativeLimits(), **limits))
    assert caught.value.code == "RESOURCE_LIMIT"


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_limits(value):
    with pytest.raises(NativeError) as caught:
        NativeLimits(max_captures=value)
    assert caught.value.code == "INVALID_ARGUMENT"


def test_exact_compilation_thresholds_and_crlf():
    body = b"@section\nRoot\n  value {{ text | required }}\n@end\n"
    limits = NativeLimits(
        max_template_bytes=len(body),
        max_lines=4,
        max_line_characters=len("  value {{ text | required }}"),
        max_patterns=2,
        max_captures=1,
    )
    assert compile_native(body, limits=limits).kind == "section"
    assert compile_native(body.replace(b"\n", b"\r\n")).kind == "section"


@pytest.mark.parametrize("memory", [1, 65_535, 2_147_483_648])
def test_re2_memory_limits_reject_unusable_or_overflowing_values(memory):
    with pytest.raises(NativeError) as caught:
        NativeLimits(max_re2_memory=memory)
    assert caught.value.code == "INVALID_ARGUMENT"


def test_unescaped_embedded_regex_quotes_rejected():
    with pytest.raises(NativeError) as caught:
        compile_native(b'@section\nRoot\n  value {{ text | regex="a" "b" }}\n@end')
    assert caught.value.code == "INVALID_TEMPLATE"
