# Native parser: experimental implementation

Native proves the synthetic P0-01, P0-02 and all four P1 cases from
[the corpus](../../tests/profiles/cisco/nxos/cli/README.md). It is not a certified
NX-OS grammar, an operational Profile or a public collection API. Offline
qualification measurements do not imply real-device proof, JMESPath execution,
schema validation or Profile activation. P2-02 and P2-03 reproduce distinct approved
hierarchical oracles. The owner authorized removal of P2-02's historical
flat oracle; P2-03's historical flat oracle remains unchanged.
Internal parser APIs are not new root/contracts exports.

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
  description {{ description | phrase }}
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

Exactly one unnamed root `@section` or `@record` contains its header, optional
body fields and optionally named child blocks. The common `@end` closes the
most recent declaration. Directives occupy separate lines and may have visual
spaces/tabs before them; that indentation has no CLI or JSON meaning. Directive
suffixes are not normalized: a child name uses one ASCII space after the keyword,
and trailing directive whitespace is rejected. Blank
lines and whole-line `#` comments are ignored in Native source, not removed
from extracted resources. Patterns retain their literal indentation: the root
header is unindented, child headers and parent fields share one deeper prefix,
and child fields use one further prefix. Prefixes are exact strings; tabs are
not expanded. Unmatched directives, unnamed children, unknown modifiers and
trailing template-pattern whitespace are errors.

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

### Explicit child contexts

```text
@record
parent {{ id }}
  owner {{ owner }}
  @record items
  item {{ item }}
    value {{ value | required }}
  @end
  @section details
  details {{ label }}
    note {{ note | phrase | optional }}
  @end
@end
```

Children need unique ASCII identifier property names, without collisions with
parent captures. Named child records always emit an array, even when empty;
child sections are omitted when absent and may occur at most once per parent.
Parent fields and direct child headers are evaluated together, without a
priority. Parent captures are not copied to children. Equal parent names remain
separate occurrences; parent/child order and duplicate records are preserved.

Only two declaration levels are supported: root and immediate children. A
sibling line closes the active child first; a top-level line closes the whole
parent, even when unrelated. EOF closes descendants before ancestors. Required
and duplicate state belongs to each occurrence. Blank lines do not close scopes.
In hierarchical templates an unrelated or unselected member starts a skipped
subtree: deeper lines cannot populate a parent or another child. Selection and
diagnostics resume at its indentation or an ancestor. There is no implicit
dedent, joining, grouping, ancestor-field lookup or network-specific grammar.
Flat 40B templates retain their existing unrelated-line handling.

Captures have ASCII identifier names and return unchanged strings unless an
explicit transformation is declared:

Header captures cannot use `optional` or `required`; these modifiers apply only
to body patterns.

| Syntax | Meaning |
| --- | --- |
| `{{ value }}` | One nonempty token |
| `{{ value \| phrase }}` | Text, including spaces, with deterministic boundaries |
| `{{ value \| regex="..." }}` | Entire allocated segment must RE2-fullmatch |
| `{{ value \| optional }}` | Inline segment may be absent, not the whole field line |
| `{{ value \| required }}` | Field pattern must occur; cannot combine with `optional` |

`ignore` is a reserved name with exactly the same matching and modifiers but
no JSON emission. All six token/phrase/regex, mandatory/optional forms are
supported in body patterns. Multiple ignored captures use positional slots, not a shared field.
Ignored data still undergoes validation and transformations and consumes their
budgets before discard.

### Deterministic capture composition

Mandatory token captures have whitespace-delimited boundaries. Token captures
may precede other tokens or literal words. One terminal `phrase` or regex capture
may contain spaces. One terminal optional token/phrase/regex segment is allowed.
A nonterminal phrase/regex requires a subsequent non-whitespace literal
delimiter, no other flexible capture and no optional captures on that line.
Multiple occurrences of that delimiter in the allocated suffix fail as
ambiguous, before validating captures; neither greediness nor suffix validation
chooses a boundary. Embedded or adjacent captures without whitespace boundaries
are unsupported. There is no general capture-partition search. `rest` is rejected;
there is no compatibility alias.

Literal horizontal-whitespace runs match one or more spaces/tabs. Immediately
before terminal phrase/regex, exactly **one** space/tab is structural; all remaining
characters belong to the capture. An optional segment owns its separator:
absence requires no separator; a separator with an empty phrase/nullable-regex
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
version still fails at closure. Root-header constraints select emission only:
`interface port-channel10` closes an Ethernet block even when it fails the
Ethernet regex selection.

### Validation and explicit transformations

The pipeline is allocation, validation of original strings, unique complete
pattern selection, transformation, then immutable JSON emission. A capture has
at most one predefined validator or authored RE2 constraint. Validation after
transformation and incompatible types fail at compilation, including
`IPV4 | to_int`. A transformation failure never selects another pattern.

`IPV4` and `IPV6` use `ipaddress` address validation. `PREFIXV4` and `PREFIXV6`
require explicit numeric CIDR lengths without leading zeros (except `0`), and
use interface validation so host bits are allowed. Dotted masks, zone IDs and
bracketed addresses are rejected. There is no unicast/public-address filter and
no normalization: spelling and host bits remain unchanged.

`INT` validates `[+-]?[0-9]+` without conversion. `to_int` explicitly converts
that grammar, accepting signs and leading zeros, but no trimming, underscores
or Unicode digits. Conversion is capped at 640 digits, excluding the sign,
without changing interpreter settings.

- `split(",")`: string to string array; exact nonempty literal separator,
  retaining empty entries, order and duplicates.
- `expand_ranges("-")`: string array to string array; inclusive nonnegative
  ASCII decimal ranges, rejecting malformed/reversed ranges. Standalone strings
  remain unchanged; generated numbers have ordinary decimal spelling. Range
  delimiters cannot contain decimal digits. Cardinality and serialized size
  are checked before allocating expanded strings.
- `map_int`: string array to integer array, using the same strict conversion.
  It does not expand ranges. Empty or space-prefixed entries fail conversion.

Delimiters use double quotes with only `\"` and `\\` escapes. Empty delimiters
and all Unicode category `Cc` characters (C0, DEL and C1 controls) are rejected
consistently by `split` and `expand_ranges`. Other Unicode categories are not
rejected by that rule; no delimiter normalization occurs. This restriction does
not apply globally to captured text, regexes or CLI indentation. No regex
splitting, evaluation, plugin or custom function mechanism exists. For example:

```text
switchport trunk allowed vlan {{ vlans | split(",") | expand_ranges("-") | map_int }}
```

The cumulative transformed-item budget counts every intermediate array element
produced by `split`, `expand_ranges` and `map_int`, including ignored captures
and separate records. Thus `1-2` through those three steps consumes five items.
This is not a VLAN limit. Intermediate values also obey the output-byte ceiling.

### Deterministic child-record alternatives

Only a named child `@record` accepts consecutive complete header alternatives,
at its header's literal CLI indentation. Deeper patterns begin the shared body;
an alternative cannot follow a body field. No leading `|` or `@or` marker exists.
For example:

```text
@record
vrf context {{ vrf }}
  @record routes
  ip route {{ prefix | PREFIXV4 }} {{ next_hop | IPV4 }}
  ip route {{ prefix | PREFIXV4 }} {{ next_hop | IPV4 }} name {{ name }}
  ip route {{ prefix | PREFIXV4 }} {{ next_hop | IPV4 }} name {{ name }} tag {{ tag | INT | to_int }}
  ip route {{ prefix | PREFIXV4 }} {{ interface | phrase | regex="Null0" }} name {{ name }}
  ip route {{ prefix | PREFIXV4 }} {{ interface }} {{ next_hop | IPV4 }} track {{ track | INT | to_int }} name {{ name }}
  @end
@end
```

All complete alternatives and validators are evaluated independently of
declaration order. Exactly one accepted pattern is transformed and emitted.
Multiple accepted patterns fail with `AMBIGUOUS_MATCH`, even for identical
values. No accepted pattern but a recognized invalid or suffixed structure
fails with `MALFORMED_LINE`. This closed grammar applies with one header too;
adding another header does not change validation policy. A transformation error
does not retry another header. Unrelated structures follow subtree isolation.
Root-header filtering and optional child-section selection remain distinct.

Entirely literal child-record headers follow the same closed grammar: for
`ready state`, `ready state extra` and trailing undeclared spaces/tabs are
malformed. `ready other`, `ready stateful` and `readyX state extra` remain
foreign structures. Literal whitespace runs retain their normal space/tab
matching, without trimming. A uniquely accepted longer declared alternative
still wins over a shorter header's diagnostic. Root headers, child sections
and skipped subtrees are unchanged; there is no first-word targeting.

Trivially identical structural matchers are rejected at compilation, even when
capture names, validators or transformations differ. This is deliberately not a
general regex-intersection solver. Other overlaps are runtime errors, never a
priority or specificity choice. Optional literal clauses and observed attribute
orders require complete explicit alternatives; no arbitrary permutation or
inline optional-group mechanism is provided.

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
| Selected blocks, globally across parents and children | 10,000 |
| Cumulative transformed array elements | 10,000 |
| Output UTF-8 bytes | 8,388,608 |

Output size is measured as compact JSON with UTF-8 strings and standard JSON
escaping, including keys and punctuation, before defensive freezing. Limits
include empty child arrays and nested object/property punctuation. Two block
levels and fixed capture-result types bound output to five container levels,
below the shared JSON freezer's 64-container ceiling. Template pattern/capture
budgets apply across all declarations, not separately to each child. Limits
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

## Offline qualification and measurements (40D)

The [benchmark script](../../tools/benchmark_native.py) uses the standard
library and the installed Native engine. Run it outside ordinary CI on Linux,
with Python 3.12 as the reference measurement interpreter:

```bash
uv run --no-sync python tools/benchmark_native.py \
  --environment-note "Shared Linux host; concurrent load is not controlled" \
  > /path/outside/checkout/native-benchmark.json
```

The caller supplies an existing writable output directory. Failed workers,
wrong results and changed local sources abort the campaign; do not treat an
incomplete output file as evidence. There is a 600-second worker safety timeout,
not a parser performance requirement. No network device or host-wide settings
are involved.

The default campaign uses five warmups, thirty timing samples, five independent
cold-compilation workers and three independent workers per memory method/case.
Workers run sequentially with `PYTHONHASHSEED=0`, normal GC and untouched RE2
caches. Each timed observation contains one operation. Use repeated `--case`
selectors for a smaller investigation; sampling overrides are recorded.

### Workloads and verification

The generated corpus is vendor-independent and deterministic:

- Flat parsing: 100, 1,000 and 10,000 records.
- Hierarchical parsing: the same total selected-block counts, each split into
  10% parents and 90% children. Three child alternatives share a required body;
  parent fields, literal headers and integer conversion are exercised.
- Transformations: split-only, split/expand, split/map and split/expand/map.
  The full range pipeline produces 4,999 integers and consumes 9,999 intermediate
  items. Split/map consumes exactly 10,000 items.
- Rejections: 10,001 required intermediate items, 10,001 attempted selected
  blocks, late malformed capture structure and late ambiguous child selection.

Default limits are never increased. Counts for rejected workloads describe
required/attempted totals, not partial returned data. Expected structures are
generated independently of Native; comparisons serialize types explicitly and
preserve array order. Error codes and numeric lines are checked too.

### Distinct measurement scopes

| Campaign | Scope |
| --- | --- |
| Cold compilation | First Native compilation inside each fresh interpreter, after imports and case generation; Python startup is excluded |
| Repeated compilation | Same body after warmup, with the binding's ordinary cache effects |
| Parsing | Precompiled template; includes normal matching, validation, conversion and defensive freezing |
| Python allocations | Separate fresh worker, tracing starts after case/oracle preparation and parser precompilation; one operation without warmup |
| Peak RSS | Separate fresh worker; Linux `/proc/self/status` `VmHWM` kB converted to bytes, post-`exec` address-space peak through the operation |
| Retention observation | Repeated hierarchy-1,000 parses after warmup; release outputs and collect GC before recorded checkpoints |

Elapsed and process CPU durations use `perf_counter_ns` and `process_time_ns`.
Case generation, imports, external serialization, result verification and
returned-output cleanup are outside operation timing. Raw samples and
median/IQR/population-standard-deviation/minimum/maximum summaries retain their
units in metric names.

Python tracing does not measure all native RE2 allocations. Allocation
observations include the returned result while alive; retention checkpoints
instead follow its release. Tracing and checkpoint bookkeeping have overhead.
Retention peaks also include verification performed between checkpoints.
RSS includes the interpreter, libraries, case/oracle preparation and compilation,
not just Native. Linux `ru_maxrss` is also recorded as `rusage_maxrss_bytes`:
it can retain the launcher's pre-`exec` high-water even in a fresh interpreter.
Keep that raw counter distinct from `rss_peak_bytes` (`VmHWM`); neither is
Native-only memory. Do not subtract independent peaks and call the difference
parser memory. RSS high-water marks and allocator/cache plateaus are not by
themselves proof of a leak.

The JSON report records commands, UTC timestamps, Python/dependency versions,
CPU/OS/libc, exposed resource constraints, initial/final load, dataset hashes,
sizes, patterns, captures and budgets. Missing cgroup files are explicitly
reported as not exposed. Uncommitted source identity is the baseline/head SHA
**plus the complete local-patch SHA-256, including untracked files**; it is not
a new commit SHA. Keep reports outside the checkout so they do not change that
patch. Review artifacts should retain the raw report and matching patch.

### Qualification boundaries

Use `PASS` only for demonstrated behavior or a completed valid measurement
protocol, `FAIL` for a reproduced contract violation, `NOT_VERIFIED` for
insufficient evidence, and `DEFERRED` for explicitly excluded work.
The review scorecard must identify evidence for the eight approved golden
scenarios, literal-header diagnostics, Cc delimiters, contexts/failure recovery,
combined limits, interprocess determinism, immutability, measurements,
Python 3.11/3.12/3.15 compatibility and installed wheel/sdist checks.

The first campaign establishes descriptive observations, not an absolute
latency, throughput or memory gate. No production SLO or performance superiority
is established. A completed measurement protocol can pass while production
performance suitability remains `NOT_VERIFIED`. Real devices, official Features
and future integrations remain separate qualifications.

## Deferred

Arbitrary route attribute permutations, global-route coverage, richer nesting
and generalized capture partitioning are not delivered. Profile dispatch,
JMESPath, schemas, Registry activation and collection remain outside Native.
No hard CPU deadline, process-RSS cap, free-threaded or cross-platform
performance guarantee follows from this offline qualification.
