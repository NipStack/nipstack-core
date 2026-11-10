"""Strict, engine-independent extraction of an already acquired template resource."""

from typing import Literal

from nipstack_core.contracts.errors import NipStackCoreUsageError


class TemplateResourceError(NipStackCoreUsageError):
    """Sanitized envelope failure, without resource contents or decoder exceptions."""

    def __init__(
        self,
        code: Literal["INVALID_ARGUMENT", "INVALID_ENCODING", "INVALID_ENVELOPE", "RESOURCE_LIMIT"],
    ) -> None:
        self.code = code
        super().__init__(
            {
                "INVALID_ARGUMENT": "Template resource arguments are invalid.",
                "INVALID_ENCODING": "Template resources must use UTF-8 without a BOM.",
                "INVALID_ENVELOPE": "The template resource envelope is invalid.",
                "RESOURCE_LIMIT": "A template resource limit was exceeded.",
            }[code]
        )


def extract_template_body(resource: bytes, *, max_bytes: int) -> bytes:
    """Return the exact body byte slice; no filesystem access or engine interpretation.

    Only standalone, unindented delimiter lines are structural. An optional doc
    block precedes one template block. LF and CRLF remain unchanged in the body.
    """
    if not isinstance(resource, bytes) or type(max_bytes) is not int or max_bytes <= 0:
        raise TemplateResourceError("INVALID_ARGUMENT")
    if len(resource) > max_bytes:
        raise TemplateResourceError("RESOURCE_LIMIT")
    valid = True
    try:
        resource.decode("utf-8")
    except UnicodeDecodeError:
        valid = False
    if not valid or resource.startswith(b"\xef\xbb\xbf"):
        raise TemplateResourceError("INVALID_ENCODING")
    if b"\r" in resource.replace(b"\r\n", b""):
        raise TemplateResourceError("INVALID_ENVELOPE")

    state = "before"
    documented = False
    start = end = None
    offset = 0
    tags = (b"<doc>", b"</doc>", b"<template>", b"</template>")
    for raw in resource.splitlines(keepends=True):
        line = raw.removesuffix(b"\n").removesuffix(b"\r")
        if state == "before" and line == b"<doc>" and not documented:
            state = "doc"
            documented = True
        elif state == "doc" and line == b"</doc>":
            state = "before"
        elif state == "before" and line == b"<template>":
            state = "template"
            start = offset + len(raw)
        elif state == "template" and line == b"</template>":
            state = "after"
            end = offset
        elif line in tags or (state in ("before", "after") and line.strip()):
            raise TemplateResourceError("INVALID_ENVELOPE")
        offset += len(raw)
    if state != "after" or start is None or end is None:
        raise TemplateResourceError("INVALID_ENVELOPE")
    return resource[start:end]
