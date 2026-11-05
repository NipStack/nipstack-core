# Internal Profile models and secure loading

30A provides typed in-memory definitions in `nipstack_core.profiles`. They are
**internal preparatory data**, not a stable public API, a YAML loader, a
validated Registry or active Profiles. The approved contract is recorded in
[Issue #16](https://github.com/NipStack/nipstack-core/issues/16).

30B adds the internal Linux loader described below, under
[Issue #22](https://github.com/NipStack/nipstack-core/issues/22). A loaded Profile
is still neither fully validated nor active.

The 33 root/contracts public exports and the contracts described in
[20-public-contracts.md](20-public-contracts.md) are unchanged. Features have no
scope classification or replacement.

## Ownership and constructors

- `profiles/actions.py`: artifacts, CLI context/Actions and HTTP request/Actions.
- `profiles/features.py`: Feature inputs and lexical parser/schema references.
- `profiles/profile.py`: metadata, connection, fingerprint and Profile composition.

All eleven dataclasses are frozen, slotted, keyword-only, structurally equal and
explicitly unhashable. The internal package also imports the Action union:

```text
ActionDefinition = CLIActionDefinition | HTTPActionDefinition

ArtifactDefinition(*, kind: str, expose_by_default: bool = False)
CLIContextDefinition(*, enter: Sequence[str] = (), exit: Sequence[str] = ())
CLIActionDefinition(*, action_id: str, command: str, artifact: ArtifactDefinition,
                    context: CLIContextDefinition | None = None,
                    operation_timeout: float | None = None)
HTTPRequestDefinition(*, path: str, method: Literal["GET", "POST"] = "GET",
                      query: Sequence[tuple[str, str]] | None = None,
                      headers: Mapping[str, str] | None = None,
                      body: JSONDocument | None = None)
HTTPActionDefinition(*, action_id: str, request: HTTPRequestDefinition,
                     artifact: ArtifactDefinition, operation_timeout: float | None = None)
ParserDefinition(*, engine: Literal["native", "jmespath"], template: str)
FeatureDefinition(*, feature_id: str, inputs: Sequence[str],
                  parser: ParserDefinition, schema: str)
ProfileMetadata(*, name: str, vendor: str, platform_id: str, access_variant: str)
ConnectionDefinition(*, connector: Literal["ssh", "http"], driver: str | None = None,
                     authentication: str | None = None, session_setup: Sequence[str] = (),
                     connect_timeout: float | None = None, operation_timeout: float | None = None)
FingerprintDefinition(*, action_id: str, include: Sequence[str], exclude: Sequence[str] = ())
ProfileDefinition(*, profile_id: str, version: str, metadata: ProfileMetadata,
                  connection: ConnectionDefinition, actions: Mapping[str, ActionDefinition],
                  features: Mapping[str, FeatureDefinition], spec_version: Literal[1] = 1,
                  fingerprint: FingerprintDefinition | None = None)
```

CLI and HTTP Actions have fixed `type` fields, respectively `"cli"` and `"http"`,
excluded from constructor parameters. No model encodes, acquires, compiles or
activates anything.

## Local invariants

### Identity and connection

Profile and platform IDs have one or more dot-separated ASCII
`[a-z][a-z0-9_]*` segments. They are preserved verbatim, never split to infer
transport, vendor or access variant. Action IDs, artifact kinds and
driver/authentication/access-variant selectors are single such tokens.
Feature IDs reuse exactly the three-segment 20A grammar; Modes are not closed.

Profile `version` requires SemVer 2.0.0, including valid prerelease/build
identifiers. No normalization, numeric conversion, comparison or version
selection occurs. `spec_version` is integer `1`, not bool, and is distinct from
both Profile and package versions. This stricter definition does not change
opaque `ProfileIdentity` or `CollectionRequest` validation.

Metadata name/vendor are nonempty strings without peripheral whitespace,
control characters or Unicode surrogates. A Profile has one primary Connector:
`ssh` or `http`. Driver and Session setup apply only to SSH; the optional
authentication field applies only to HTTP and is a strategy selector, not auth
data. Missing or unknown lexical selectors do not prove a working capability or
authorize implicit authentication. No endpoint or credential fields exist.

CLI command, context and Session setup values are nonempty single-line strings
with the same text checks. Sequences preserve repetitions and order. No commands
are executed. Optional timeouts reuse existing positive finite seconds
validation, rejecting bool, zero, invalid/nonfinite numbers and oversized
integers, and converting compatible integers to floats. `None` means no
declaration/override, not unlimited operation.

### HTTP declarations

Only **GET** (default) and **POST** are permitted:

- GET requires `body=None`, including when the alternative would be an empty object/array.
- POST permits no body or a JSON object/array, including legitimate empty documents.
- A method is not a safety classification: POST can consult and GET can have
  equipment-side effects. There is no `read_only` field.

`path` is an ASCII origin-relative URI path beginning with `/`, not `//`. It
cannot contain an origin, query, fragment, whitespace, backslash or literal dot
traversal segments. Percent escapes require two hexadecimal digits; encoded
ASCII controls, spaces, slash/backslash and encoded dot traversal are rejected.
The supplied path is preserved, not resolved or normalized. Lexical checks do
not establish server interpretation, redirect safety or protection against
multiple decoding by a server.

`query` accepts a sequence of **tuple pairs of strings**, not a mapping, string,
generator or list of list pairs. Names are nonempty; values may be empty.
Strings allow Unicode scalars without control characters, including literal
reserved characters and spaces. Order, case and repeated names are preserved.
No coercion, trimming, deduplication, pre-decoding or encoding occurs.
`None` and empty sequences become `()`.

For future request construction, values are raw text: UTF-8 percent-encoding
applies separately to names and values, with space `%20`, plus `%2B`, percent
`%25` and escaped reserved characters. For example:

```python
query = [
    ("item", "a/b"),
    ("item", "c+d"),
    ("filter", "a b&é"),
    ("empty", ""),
    ("literal", "%2F"),
]
```

Its future encoded form is:

```text
item=a%2Fb&item=c%2Bd&filter=a%20b%26%C3%A9&empty=&literal=%252F
```

30A contains no query encoder, URL builder or client. Query values cannot appear
in the `path` field instead of structured pairs.

Headers have HTTP token names and ASCII field values (printable ASCII or
horizontal tab, including empty values), without CR/LF or other controls.
Case-insensitive name duplicates fail; supplied spelling/values are preserved.
The internal technical allowlist initially permits only `Accept` and
`Content-Type`, without fixing their values to `application/json`.
Authentication, transport-owned and unknown vendor headers are rejected.
Adding a technical header requires a concrete reviewed non-authentication use
case, architectural approval and tests. Profiles cannot override the list.
Declared content type is not proof of the eventual body encoding.

HTTP body roots are checked locally, then frozen with the existing internal
`contracts/json_data.py` primitive, not the result serializer. Objects become
owned read-only mappings and arrays become tuples recursively. Existing JSON
rules reject non-string keys, invalid Unicode, nonfinite floats, cycles,
secrets/auth objects and arbitrary Python values. Shared acyclic subtrees are
copied separately. The existing limit is 64 containers on a path, including the
root. Arbitrary Python integers retain the existing JSON primitive semantics:
constructors neither encode them nor change interpreter digit settings.
Any future encoding failure must be surfaced explicitly at that boundary.

There are no new path/header/body length ceilings or byte budgets. Bounded
manifest decoding and resource budgets belong to 30B; effective request/response,
time and operational budgets belong to RuntimeLimits/Connectors.

### Feature resources and composition

Each Feature has its own ID, nonempty ordered unique Action `inputs`, parser and
schema reference. Multiple Features may share Actions and consume multiple
inputs. There are no commands in Features, Feature-to-Feature dependencies,
fallbacks or schema digests in definitions.

Parser engines are exactly `native` and `jmespath`. Template/schema values are
relative POSIX resource strings without absolute paths, empty/dot/traversal
components, backslashes, URI syntax or expansion syntax. No extension or
vendor-neutral schema is imposed. Existence, symlinks, actual confinement,
parser syntax, input compatibility and schema contents are not checked here.

Profile maps check contained types, agreement between keys and contained IDs,
and CLI/HTTP Action type versus primary Connector. Empty required mappings,
unknown lexical selectors and dangling input/fingerprint Action references can
exist in preparatory values. They do not constitute validated Profiles.

Fingerprint criteria are nonempty single-line strings; at least one include is
required, excludes default empty. The model performs no matching, regex
compilation or automatic Profile discovery.

Artifact kind is open semantic metadata, independent of content format.
`expose_by_default=False` is the default. A declaration is not disclosure
authorization; workstream 80 must enforce Profile opt-in **and** request
`PROFILE_DEFAULT`. No RawArtifact is produced. Future acquisition normally uses
`artifact_id == action_id`; there is no configurable artifact ID here.

## Synthetic in-memory examples

These construct real models but assert no available driver, parser resources,
official Feature or network behavior.

```python
from nipstack_core.profiles import (
    ArtifactDefinition,
    CLIActionDefinition,
    ConnectionDefinition,
    FeatureDefinition,
    FingerprintDefinition,
    HTTPActionDefinition,
    HTTPRequestDefinition,
    ParserDefinition,
    ProfileDefinition,
    ProfileMetadata,
)

cli_action = CLIActionDefinition(
    action_id="show_version",
    command="show version",
    artifact=ArtifactDefinition(kind="command_output"),
)
cli_feature = FeatureDefinition(
    feature_id="check.global.show_version",
    inputs=["show_version"],
    parser=ParserDefinition(engine="native", template="features/version/parser.yaml"),
    schema="features/version/schema.json",
)
cli = ProfileDefinition(
    profile_id="example.switch.cli",
    version="1.0.0",
    metadata=ProfileMetadata(
        name="Example Switch CLI",
        vendor="example",
        platform_id="example.switch",
        access_variant="cli",
    ),
    connection=ConnectionDefinition(connector="ssh", driver="example_cli"),
    actions={"show_version": cli_action},
    features={cli_feature.feature_id: cli_feature},
    fingerprint=FingerprintDefinition(action_id="show_version", include=["ExampleOS"]),
)

api_action = HTTPActionDefinition(
    action_id="read_status",
    request=HTTPRequestDefinition(
        path="/api/status",
        query=[("item", "first"), ("item", "second")],
        headers={"Accept": "application/json"},
    ),
    artifact=ArtifactDefinition(kind="api_response"),
)
api_feature = FeatureDefinition(
    feature_id="check.global.show_version",
    inputs=["read_status"],
    parser=ParserDefinition(engine="jmespath", template="features/version/parser.jmespath"),
    schema="features/version/schema.json",
)
api = ProfileDefinition(
    profile_id="example.switch.api",
    version="1.0.0",
    metadata=ProfileMetadata(
        name="Example Switch API",
        vendor="example",
        platform_id="example.switch",
        access_variant="api",
    ),
    connection=ConnectionDefinition(connector="http", authentication="basic"),
    actions={"read_status": api_action},
    features={api_feature.feature_id: api_feature},
)
post = HTTPRequestDefinition(
    path="/api/query",
    method="POST",
    body={"operation": "read_status"},
)
```

## Errors, immutability and deferred guarantees

Invalid local values raise `NipStackCoreUsageError`; calls outside signatures
retain native `TypeError`. Messages identify rules/fields without echoing input.
Intended repr/str hide IDs, metadata, commands, references and HTTP payloads,
showing only technical discriminants where appropriate. No credentials are
revealed or logged. A valid string can still contain sensitive information:
these models are privileged declarative knowledge, not a security sandbox.
Reflection, deliberate field access, debugger state and custom Python objects
are not protected by masked representations.

Caller-owned maps are copied even when supplied as mapping proxies. Sequences
are stored as tuples, JSON is recursively frozen, and maps preserve insertion
order. Equality ignores mapping insertion order but respects sequence order.
Unhashability is explicit; no persistent hash or cache identity is promised.

30B owns strict YAML and filesystem loading, manifest budgets and
cross-reference completeness. 30C owns the structural pipeline/preparatory
Registry; 30D with 50 owns actual resource/compiler/schema/capability and
activation gates. Parsers/Connectors/runtime workstreams own their execution
behavior. No `validated`, active flag, loader, Registry, client, resolver,
parser execution, fingerprint matcher or `collect()` is provided in 30A.

## Secure loading of one explicit directory (30B)

Import from the internal loader submodule; neither the root/contract exports nor
the existing `profiles.__all__` surface is extended:

```python
from pathlib import Path

from nipstack_core.profiles.loader import LoadLimits, load_profile

loaded = load_profile(
    Path("/explicit/local/profile"),
    limits=LoadLimits(max_total_bytes=16_777_216),
)
definition = loaded.definition
resources = loaded.resources  # Read-only relative-path -> immutable bytes.
```

`load_profile(root: Path, *, limits: LoadLimits = LoadLimits()) -> LoadedProfile`
requires an absolute directory without symlink components, including its
parents. It reads only `profile.yaml` and the explicitly referenced parser/schema
files; there is no directory scan, discovery, HOME/environment expansion,
include, inheritance, cache, source lifecycle or implicit reread.

The loader constructs the real 30A models, checks Feature inputs and fingerprint
Action existence, and acquires confined byte snapshots. Shared Actions are
allowed. Each distinct relative resource reference is acquired once. Definition
maps and sequences retain their existing ordering rules; resource order follows
first reference appearance.

`LoadedProfile` is frozen, slotted, keyword-only and unhashable. It owns its
read-only resource mapping and hides definitions/resources in its representation.
Contents remain stable if source files change after return. It is not a
certificate: direct construction of this internal value does not run the loader.

### Manifest grammar

At each closed mapping level, every unknown key fails. IDs come from their map
keys, not repeated nested fields. The complete mapping is:

| Level | Required keys | Optional keys/defaults |
| --- | --- | --- |
| Root | `spec_version`, `id`, `version`, `metadata`, `connection`, `actions`, `features` | `identification=null` |
| Metadata | `name`, `vendor`, `platform_id`, `access_variant` | None |
| Connection | `connector` | `driver=null`, `authentication=null`, `session_setup=[]`, `connect_timeout=null`, `operation_timeout=null` |
| CLI Action | `type: cli`, `command`, `artifact` | `context=null`, `operation_timeout=null` |
| CLI context | None | `enter=[]`, `exit=[]` |
| HTTP Action | `type: http`, `request`, `artifact` | `operation_timeout=null` |
| Artifact | `kind` | `expose_by_default=false` |
| HTTP request | `path` | `method=GET`, `query=null`, `headers=null`, `body=null` |
| Feature | `inputs`, `parser`, `schema` | None |
| Parser | `engine`, `template` | None |
| Identification | `action`, `match` | None |
| Identification match | `include` | `exclude=[]` |

`id` maps to `profile_id`; Action/Feature map keys become their contained IDs.
`type` selects the Action class and is not passed as a constructor argument.
`identification.action` and `match.include/exclude` map to the existing
`FingerprintDefinition`. No alternate Python-field-name aliases exist.

`spec_version` is mandatory integer `1`, not bool or float. Actions and Features
are mandatory mappings but may be empty: loading is not activation. Inputs and
fingerprint includes remain nonempty according to 30A. Unknown fields, including
legacy Feature `scope`, are rejected, not ignored.

Absent optional fields use exactly the defaults above. Explicit `null` is
permitted only for identification, driver/authentication selectors, timeouts,
CLI context, query, headers and body. It is forbidden for method, exposure bool
and all command/criterion sequences. Query/header `None` is passed to the 30A
constructor, which already normalizes it to an immutable empty collection.
There is no loader fallback from `null` to `[]`, `{}`, `false` or another default.
`context: {}` constructs an empty context, distinct from `context: null`.

Query is an ordered YAML sequence of two-string sequences:

```yaml
query:
  - ["item", "a/b"]
  - ["item", "c+d"]
  - ["empty", ""]
  - ["filter", "a b&é"]
  - ["literal", "%2F"]
```

Each pair is explicitly adapted to a Python tuple. No value coercion,
deduplication, trimming or URL encoding occurs. Numeric query values require
quotes. HTTP method/body/path/header rules remain exactly those of 30A.
Arbitrary JSON body properties are data, not additional manifest fields.

### Synthetic CLI and HTTP manifests

The following declares no proven driver, parser language or valid Schema:

```yaml
spec_version: 1
id: example.switch.cli
version: "1.0.0"
metadata:
  name: Example Switch CLI
  vendor: example
  platform_id: example.switch
  access_variant: cli
connection:
  connector: ssh
  driver: example_cli
actions:
  show_version:
    type: cli
    command: show version
    artifact: {kind: command_output}
features:
  check.global.show_version:
    inputs: [show_version]
    parser: {engine: native, template: features/version/parser.data}
    schema: features/version/schema.data
identification:
  action: show_version
  match:
    include: [ExampleOS]
```

Both resource paths must identify readable regular files under the root:

```yaml
spec_version: 1
id: example.switch.api
version: "1.0.0"
metadata:
  name: Example Switch API
  vendor: example
  platform_id: example.switch
  access_variant: api
connection:
  connector: http
  authentication: basic
actions:
  read_status:
    type: http
    request:
      path: /api/status
      query: [["item", "first"], ["item", "second"]]
      headers: {Accept: application/vendor+json}
    artifact: {kind: api_response}
  query_details:
    type: http
    request:
      method: POST
      path: /api/query
      body: {operation: read_details, filters: [{enabled: true}]}
    artifact: {kind: api_response}
features:
  check.global.status:
    inputs: [read_status, query_details]
    parser: {engine: jmespath, template: features/status/parser.data}
    schema: features/status/schema.data
```

### Restricted YAML decoding

PyYAML parses syntax once through its Python `BaseLoader` event API. A small
subclass rejects directive tokens before PyYAML can silently discard unknown
directive names. No YAML constructors, resolver callbacks or executable objects
are used. The loader only assembles mappings, lists and allowed scalars.

- UTF-8 only; one initial UTF-8 BOM is accepted and counted. UTF-16/32 and
  malformed Unicode fail. Exactly one nonempty mapping document is required.
- Anchors (even unused), aliases, explicit tags (including standard tags),
  all directives (known or unknown), complex/non-string keys and duplicate keys fail.
- Plain `<<` mapping keys fail; quoted `"<<"` may be ordinary JSON body data.
- Quoted/block scalars stay strings after YAML escape/folding processing.
- Plain lowercase `null`, `true`, `false` become None/bools. Empty implicit
  values such as `driver:` fail; write `null` explicitly.
- Integers and floats use JSON decimal spelling; floats must be finite.
  `.nan`/`.inf` spellings are rejected unless quoted.
- Other plain values remain strings: `yes`, `on`, `True`, dates, `012`, `0x10`
  and `1_000` are not YAML 1.1 conversions. Field types are checked afterwards.

This is a restricted Profile format, not a claim to implement all YAML 1.1/1.2
scalar semantics. Duplicate detection uses decoded strings, including keys
whose escape spellings differ.

### Per-load resource budgets

`LoadLimits` is frozen, slotted and keyword-only. All eleven fields require
strictly positive Python integers, excluding bool; no coercion or "unlimited"
sentinel exists. Only the Python caller configures them, never the manifest.

| Field | Default | Accounting |
| --- | ---: | --- |
| `max_manifest_bytes` | 1,048,576 | Raw manifest bytes, BOM/comments included |
| `max_resource_bytes` | 2,097,152 | Raw bytes of each referenced resource |
| `max_total_bytes` | 16,777,216 | Manifest plus distinct resource bytes |
| `max_yaml_depth` | 80 | Containers on a manifest path, root included |
| `max_yaml_nodes` | 100,000 | Mapping/sequence/scalar events, keys included |
| `max_scalar_bytes` | 65,536 | UTF-8 bytes of each decoded scalar/key |
| `max_actions` | 256 | Entries before constructing Action models |
| `max_features` | 1,024 | Entries before constructing Feature models |
| `max_resource_files` | 2,048 | Distinct declared parser/schema paths |
| `max_path_components` | 32 | Relative path segments, leaf included |
| `max_integer_digits` | 512 | Decimal integer digits, sign excluded |

Overlapping ceilings apply independently; the total may be configured below an
individual file ceiling. Limits need not be simultaneously attainable.
Reference repetitions reuse snapshots; different paths are counted separately
even if they identify one inode. If `profile.yaml` is referenced as a resource,
its bytes are reused and counted only once, while its resource ceiling applies.

File sizes are checked before reading, then every read is bounded by the
remaining individual/total allowance plus at most one overrun-detection byte.
No truncation, automatic retry or partial success is returned.

Node/depth limits precede insertion into the decoded tree. PyYAML has already
materialized a scalar before its scalar budget can be checked; the manifest
byte ceiling still bounds input. Action/Feature limits precede model
construction, not allocation of the already bounded decoded YAML mappings.
These are not process RSS or CPU deadlines. Values are provisional, not
empirically optimized, and are separate from future RuntimeLimits.

The body JSON limit remains 64 containers, independent of manifest wrappers;
64 body levels plus four envelope containers fit within YAML depth 80.
The integer budget is checked before conversion and also respects CPython's
active integer-conversion guard, without changing or bypassing global settings.
Raising a caller budget does not remove that interpreter constraint.

### Linux filesystem checks and residual limits

Unsupported platforms/primitives fail before opening files; there is no weaker
portable fallback. Directory components, including root parents, are opened
relative to pinned descriptors with `O_DIRECTORY`, `O_NOFOLLOW` and `O_CLOEXEC`.
Leaf metadata is checked without following links, then the opened descriptor is
verified as regular. `O_NONBLOCK` avoids waiting on a substituted FIFO. Missing,
unreadable, linked and non-regular resources fail explicitly. All descriptors
close on success or error.

File device/inode, mode, size, mtime and ctime are compared before opening,
before reading and after reading. Size/content-length mismatches and observable
changes fail. This is not a multi-file atomic snapshot or an integrity proof.
Hard links, bind mounts, hostile subtree renames and all concurrent writes are
not sandboxed. A device substitution may briefly open a device before the
post-open regular-file check; nonblocking flags do not make devices harmless.
Regular-file I/O can still block on an unhealthy filesystem. Use a controlled
local tree during acquisition. Returned snapshots need no filesystem trust
after return, but can themselves contain sensitive data.

### Failures and remaining gates

`ProfileLoadError` derives from `NipStackCoreUsageError` and exposes internal
technical `code`, optional controlled `field`, and optional one-based YAML
`line`/`column`. Its fixed messages/repr do not echo YAML, IDs, paths, commands,
headers, body or resource contents. Original parser/OS messages are not emitted.
No raw data is logged. The first failure follows deterministic pipeline order;
this is not 30C issue aggregation or necessarily the earliest textual defect.

Codes are `INVALID_ARGUMENT`, `UNSUPPORTED_PLATFORM`, `IO_ERROR`,
`INVALID_ENCODING`, `INVALID_YAML`, `INVALID_MANIFEST`, `INVALID_REFERENCE`,
`UNSAFE_PATH`, `RESOURCE_LIMIT`, `RESOURCE_CHANGED`. No public enum was changed.

Resources remain opaque bytes, even if empty, non-UTF-8 or invalid as parsers or
Schemas. No extension convention, parser/input capability check, template
compilation, Draft 2020-12 validation, regex/fingerprint execution or
SchemaIdentity calculation is performed. 30C and 30D/50 retain their gates.
Loaded Profiles must never be treated as operational.
