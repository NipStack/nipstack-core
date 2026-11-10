# Native parser: experimental 40B implementation

Native currently proves only the synthetic P0-01, P0-02 and P1-04 cases from
[the corpus](../../tests/profiles/cisco/nxos/cli/README.md). It is not a certified
NX-OS grammar, an operational Profile or a public collection API. No benchmark,
real-device proof, JMESPath execution, schema validation or Profile activation
is implied. Internal parser APIs are not new root/contracts exports.

## Resource and preparation boundary

The Profile loader still acquires **opaque bytes**. Call the shared extractor
explicitly before compilation:

```python
from nipstack_core.parsers.native.compiler import compile_native
from nipstack_core.parsers.native.runtime import parse_native
from nipstack_core.parsers.template_resource import extract_template_body

resource = b"""<doc>
Synthetic example.
</doc>
<template>
@record
item {{ id | regex="[A-Z]+" }}
  description {{ description | rest }}
@end
</template>
"""
prepared = compile_native(extract_template_body(resource, max_bytes=4096))
data = parse_native(prepared, "item LAB\n  description example\n")
assert data == ({"id": "LAB", "description": "example"},)
```

Resources use strict UTF-8 without a BOM and LF or CRLF. Delimiters are exact,
unindented, standalone lines without attributes. An optional single `<doc>`
precedes exactly one `<template>`; only whitespace is allowed outside. Reserved
delimiter lines cannot nest or occur literally in the body. There is no XML
parser, entity substitution, dedenting or newline normalization. The extractor
returns the exact byte slice between template delimiter lines, including any
final newline. Documentation is not compiled. The same extractor will serve
JMESPath; engine dispatch and Profile integration remain future work.

## Native grammar and matching

Exactly one root `@section` or `@record`, followed by its header pattern and
zero or more consistently indented body patterns, ends with the common `@end`.
Directives occupy separate unindented lines. Blank lines and whole-line `#`
comments are ignored in Native source, not removed from extracted resources.
Header indentation is forbidden; all body patterns use the same exact sequence
of spaces/tabs. A recognized input body line must use that indentation.
Unmatched or extra directives, nested roots, unknown modifiers and trailing
template-pattern whitespace are errors.

- `@section` produces one frozen JSON object. A missing or duplicate selected
  section fails.
- `@record` produces a frozen JSON array (tuple), including zero or one records.
  A selected header alone creates a record. Preserve source order and identical
  separate records. An empty result (`[]`, internally `()`) means no record was
  selected, including when input is nonempty. It does not validate the entire
  source configuration; unrelated or unselected blocks are not implicitly
  validated.
- Every nonblank top-level input line closes the preceding block **before**
  selection, even if the new header is foreign or unrecognized. EOF closes it
  too; it does not prove upstream transport completeness. Blank lines do not.
- Body patterns are unordered and optional by default. `required` requires
  that field pattern to occur before closure. A repeated pattern or repeated
  emitted scalar name in one block fails, including equal values.

Captures have ASCII identifier names and return unchanged strings:

Header captures cannot use `optional` or `required`; these modifiers apply only
to body patterns.

| Syntax | Meaning |
| --- | --- |
| `{{ value }}` | One nonempty token |
| `{{ value \| rest }}` | Entire remaining line, including trailing spaces |
| `{{ value \| regex="..." }}` | Entire allocated segment must RE2-fullmatch |
| `{{ value \| optional }}` | Inline segment may be absent, not the whole field line |
| `{{ value \| required }}` | Field pattern must occur; cannot combine with `optional` |

`ignore` is a reserved name with exactly the same matching and modifiers but
no JSON emission. All six token/rest/regex, mandatory/optional forms are
supported in body patterns. Multiple ignored captures use positional slots, not a shared field.
Ignored data still consumes input and matching budgets.

### Deterministic capture composition

Mandatory token captures have whitespace-delimited boundaries. Token captures
may precede other tokens or literal words. One terminal `rest` or regex capture
may contain spaces. One terminal optional token/rest/regex segment is allowed.
Nonterminal rest/regex/optional captures, embedded or adjacent captures without
whitespace boundaries, and unsupported compositions fail **at compilation**.
There is no general capture-partition search.

Literal horizontal-whitespace runs match one or more spaces/tabs. Immediately
before terminal rest/regex, exactly **one** space/tab is structural; all remaining
characters belong to the capture. An optional segment owns its separator:
absence requires no separator; a separator with an empty rest/nullable-regex
capture is present-empty, not absent. There is no competing trailing-whitespace
matcher. Empty values are never silently omitted.

Regex quoting preserves RE2 backslashes literally, for example
`regex="\[build LAB\]"`. An escaped quote remains a regex escape; pipes and braces
inside quoted expressions are not Native separators. Internal regex groups
produce no Native fields. No Python evaluation or Python `re` fallback exists.

All complete applicable patterns are checked: one accepted pattern succeeds,
multiple accepted patterns fail without priority. Full declared literal
structure with invalid capture content is malformed; competing malformed
interpretations also fail. An unrelated structure is skipped. In particular,
`NXOS: broken` does not target `NXOS: version {{ version }}`. A missing required
version still fails at closure. Header constraints select emission only:
`interface port-channel10` closes an Ethernet block even when it fails the
Ethernet regex selection.

## Errors, limits and isolation

`TemplateResourceError` and `NativeError` have fixed messages and closed codes;
Native errors may include a numeric input line, never raw values, regexes or
resource paths. Underlying decoder/RE2 exceptions are not retained as error
context. No partial data is returned on failure.

`NativeLimits` defaults:

| Budget | Default |
| --- | --- |
| Template bytes | 1,048,576 |
| Input UTF-8 bytes | 8,388,608 |
| Lines, in either template or input | 100,000 |
| Characters per line | 16,384 |
| Patterns, including header | 64 |
| Captures across all patterns | 128 |
| Authored regex UTF-8 bytes | 4,096 per constraint |
| RE2 memory setting | 524,288 per compilation |
| Selected records | 10,000 |
| Output UTF-8 bytes | 8,388,608 |

Output size is measured as compact JSON with UTF-8 strings and standard JSON
escaping, including keys and punctuation, before defensive freezing. Limits
are positive integers; RE2 memory settings below 65,536 or beyond signed
32-bit range are rejected. RE2 memory is **not** a hard RSS cap. The binding
maintains its own bounded global compilation cache (128 entries); Native adds
no cache, runtime-global state or cache purging. Native structs are frozen;
native handles can maintain internal RE2 implementation caches.

Matching remains bounded by input size, line count, number of patterns and
RE2 constraints; no hard CPU deadline is claimed. Runtime has no filesystem
or network operations. Multiple prepared templates independently parse the
same supplied string. Existing immutable JSON helpers own and freeze outputs.

## RE2 installation and Python 3.15

The dependency is the official `google-re2==1.1.20251105` (`import re2`), not
`pyre2`. Published Linux x86-64 wheels cover Python 3.11/3.12 and require
glibc 2.27 or newer. Do not co-install another distribution providing `re2`.
Neither binding types nor native implementation types enter public contracts;
the untyped dependency is confined to a narrow internal protocol boundary.

Python 3.15 has no matching published wheel at this pin. The checked-in
[source bootstrap](../../tools/re2_source.py) prepares pinned, hash-verified RE2
and Abseil sources in a **private prefix**, using C++17 and a private build-tools
environment. It then runs one supplied command with include/link settings.
No administrative install, upstream patch or custom-wheel publication occurs.
It requires Linux x86-64, `uv` and an available C++17 compiler; `CC`/`CXX` can
select private compilers. Missing prerequisites fail explicitly.

```bash
export UV_PYTHON=3.15
RE2_PREFIX="$(mktemp -d)"
uv run --no-project --python "$UV_PYTHON" python tools/re2_source.py \
  --prefix "$RE2_PREFIX" -- uv sync --locked --python "$UV_PYTHON"
uv run --no-sync pytest -q
```

Keep the prefix while using that installed environment: the extension links
to its private native library with an explicit runtime search path. Do not
move or delete it before tests and installed-distribution checks finish.
A failed/incomplete bootstrap must use a fresh empty prefix.

The published sdist switches to upstream-checkout-specific Bazel commands
when `GITHUB_ACTIONS` exists. The helper removes that variable **only in its
child command**, not globally. CI retains all 3.11/3.12/3.15 jobs and stable
required-check names. Python 3.15 builds from the locked PyPI sdist with pinned
build constraints; a local wheel supplied with `--find-links` does not replace
that locked source. The existing Python 3.12 packaging job uses official wheels.

Isolated Linux qualification demonstrated real 3.11/3.12 wheel imports and a
3.15 source build, fullmatch/regex support and rejected unsupported constructs.
Local workflow-command verification is not a remote GitHub Actions run. No
musl, free-threaded, macOS, Windows, ARM or vendor-wide qualification is implied.
Distributing a separately repaired RE2 wheel would require explicit approval
and native-runtime licensing/notice review; it is not this installation policy.

## Deferred

40C owns nesting, nonterminal flexible captures, typed conversions, VLAN lists
and routing grammar. 40D owns measured scorecards. Profile dispatch, JMESPath,
schemas, Registry activation and collection remain outside 40B.
