import pytest

from nipstack_core.parsers.template_resource import TemplateResourceError, extract_template_body


@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
@pytest.mark.parametrize("body", [b"", b"  value  \n\n", b"\\[x\\] | \xc3\xa9\n"])
def test_exact_body(ending, body):
    body = body.replace(b"\n", ending)
    resource = ending.join([b"<doc>", b"Documentation &amp;", b"</doc>", b"", b"<template>"])
    resource += ending + body + b"</template>" + ending
    assert extract_template_body(resource, max_bytes=len(resource)) == body


@pytest.mark.parametrize(
    "resource",
    [
        b"",
        b"<doc>\ntext\n</doc>",
        b"<template x>\na\n</template>",
        b" <template>\na\n</template>",
        b"<template>\na\n",
        b"<template>\n<template>\n</template>",
        b"<template>\na\n</template>\ntext",
        b"<template>\na\n</template>\n<doc>\nx\n</doc>",
        b"<doc>\na\n</doc>\n<doc>\nb\n</doc>\n<template>\n</template>",
        b"<template>\na\n</template>\n<template>\nb\n</template>",
        b"<template>\ra\r</template>",
    ],
)
def test_invalid_envelope(resource):
    with pytest.raises(TemplateResourceError, match="envelope") as caught:
        extract_template_body(resource, max_bytes=1024)
    assert caught.value.code == "INVALID_ENVELOPE"


@pytest.mark.parametrize("resource", [b"\xff", b"\xef\xbb\xbf<template>\n</template>"])
def test_encoding(resource):
    with pytest.raises(TemplateResourceError) as caught:
        extract_template_body(resource, max_bytes=1024)
    assert caught.value.code == "INVALID_ENCODING"
    assert caught.value.__context__ is None


def test_resource_limit_and_arguments():
    with pytest.raises(TemplateResourceError) as caught:
        extract_template_body(b"<template>\n</template>", max_bytes=1)
    assert caught.value.code == "RESOURCE_LIMIT"
    with pytest.raises(TemplateResourceError):
        extract_template_body(b"", max_bytes=True)


def test_jmespath_body_is_not_interpreted():
    body = b"{version: read_version.software.version}\n"
    assert extract_template_body(b"<template>\n" + body + b"</template>", max_bytes=1024) == body
