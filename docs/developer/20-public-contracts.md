# Public contracts

Public contracts are exported from both `nipstack_core` and
`nipstack_core.contracts` and depend only on the standard library. They cover
explicit Feature selection, offline connection-target data, immutable results,
request/control/event contracts, and explicit JSON-compatible result output. The accepted
initial selection contract is recorded in
[Issue #8](https://github.com/NipStack/nipstack-core/issues/8#issuecomment-6512866322).

## Explicit selection

```python
from nipstack_core import FeatureSelection, FeatureSelectionKind

everything = FeatureSelection.all()
assert everything.kind is FeatureSelectionKind.ALL
assert everything.values == ()

modes = FeatureSelection.modes("config", "check", "config")
assert modes.kind is FeatureSelectionKind.MODES
assert modes.values == ("config", "check")

features = FeatureSelection.features("check.global.show_version", "custom.network.ipv6")
assert features.kind is FeatureSelectionKind.FEATURES
assert features.values == ("check.global.show_version", "custom.network.ipv6")
```

Only `all()` selects ALL. `modes()` and `features()` require at least one value;
empty or invalid inputs never fall back to ALL. Pass strings as positional
arguments, or explicitly expand a caller-owned iterable with `*values`.

Each Mode, group, and Feature segment matches ASCII `[a-z][a-z0-9_]*`. A Mode is
one segment; a Feature ID is exactly `<mode>.<group>.<feature>`. Whitespace,
uppercase letters, Unicode, leading digits, and empty segments are rejected.
There is no trimming, case folding, or coercion.

Validation checks syntax, not availability in a Profile. `check` and `config`
are examples, not an exhaustive Mode list. Profile-based resolution and
`SELECTION_INVALID` are not implemented by this contract.

## Representation and errors

- `FeatureSelectionKind` is a standard `Enum`, not a string subclass. Its three
  members are `ALL = "all"`, `MODES = "modes"`, and `FEATURES = "features"`.
- Selections expose frozen `kind` and tuple-valued `values` fields. Exact repeats
  are removed while retaining first appearance. Caller-owned mutable containers
  are not retained.
- Equality compares kind and ordered values. Reordering identifiers changes
  equality, even if a future resolver would select the same Features. Selection
  order does not determine Action execution order.
- Equal selections have equal hashes. Hash values are not persistent identifiers
  and need not be stable between Python processes. `repr` describes the kind and
  identifiers; it is not a serialization format.
- Direct `FeatureSelection()` or `FeatureSelection(...)` construction raises
  `TypeError`. Use a factory; there is no default selection.
- `NipStackCoreUsageError`, a `ValueError` subclass, reports empty selections,
  invalid value types, or malformed identifiers without echoing received values.
  Calls outside factory signatures, such as `all("check")` or unexpected keyword
  arguments, retain Python-native `TypeError`.

Construction is enforced by an explicit `__new__` guard, not just
`dataclass(init=False)`. Private allocation initializes both frozen fields only
after a factory has established the invariants.

## Offline connection targets

The target contracts are `SecretValue`, `UsernamePasswordAuth`, `SSHKeyAuth`,
`BearerTokenAuth`, `NoAuth`, `SSHEndpoint`, `HTTPEndpoint`, `ConnectionTarget`, and
`TargetDescriptor`. Their scope is [Issue #10](https://github.com/NipStack/nipstack-core/issues/10).

```python
from nipstack_core import (
    BearerTokenAuth,
    ConnectionTarget,
    HTTPEndpoint,
    SecretValue,
)

target = ConnectionTarget(
    endpoint=HTTPEndpoint(host="api.example.invalid"),
    authentication=BearerTokenAuth(token=SecretValue("synthetic-token")),
    connect_timeout=5,
)
assert target.to_descriptor().to_dict() == {
    "scheme": "https",
    "host": "api.example.invalid",
    "port": 443,
}
```

All constructors except `SecretValue(value, /)` and `NoAuth()` take keyword-only
arguments. Invalid values raise `NipStackCoreUsageError`; calls outside the
signatures retain native `TypeError`. Validation messages identify the field or
rule without echoing inputs. Constructors perform no network or filesystem I/O.

### Endpoint syntax and options

- `SSHEndpoint(host=..., port=22, verify_host_key=True, known_hosts_file=None)`
  represents SSH, not a Profile driver.
- `HTTPEndpoint(host=..., scheme="https", port=None, verify_tls=True, ca_file=None)`
  represents an HTTP origin. `scheme` is exactly `"http"` or `"https"`.
  `effective_port` is the explicit port, or 80/443 for HTTP/HTTPS.
- Hosts are bare IPv4, unbracketed IPv6, or ASCII DNS names. DNS labels have 1-63
  characters, contain letters/digits/hyphens, and cannot start or end with a
  hyphen. The DNS name has at most 253 characters excluding one optional final
  dot. Short names and supplied ASCII IDNA names are accepted.
- URL userinfo, schemes, paths, query strings, fragments, whitespace, control
  characters, Unicode hostnames, brackets and IPv6 zone identifiers are rejected.
  Numeric IPv4 shorthand and invalid numeric address forms do not fall back to
  DNS. No trimming, case folding, DNS lookup or address canonicalization occurs.
- Ports are integers from 1 to 65535; bools are not ports. `None` is accepted
  only as an unspecified HTTP port.
- File references (`key_file`, `ca_file`, `known_hosts_file`) are nonempty
  absolute local-path strings without peripheral whitespace or control
  characters. They are preserved verbatim. No environment/home expansion,
  reading, stat, symlink resolution, permission check or format check occurs.
- TLS and SSH host-key verification are requested by default. Explicit `False`
  represents a lab/legacy verification opt-out, not verified transport security.
  Providing a trust file while disabling its verification is rejected.
- Plaintext HTTP requires neutral TLS options (`verify_tls=True`, `ca_file=None`);
  the flag does not add TLS to HTTP.

### Authentication and plaintext policy

| Form | Fields | Accepted endpoints |
| --- | --- | --- |
| `UsernamePasswordAuth` | `username`, `password: SecretValue` | SSH, HTTPS |
| `SSHKeyAuth` | `username`, `key_file`, optional `passphrase: SecretValue` | SSH |
| `BearerTokenAuth` | `token: SecretValue` | HTTPS |
| `NoAuth` | None | HTTP, HTTPS |

Usernames are nonempty strings without peripheral whitespace or control
characters. Colons are accepted: HTTP Basic-specific restrictions belong to a
future AuthStrategy, not this shared contract. Passwords and passphrases are
nonempty `SecretValue` instances and are preserved exactly, including whitespace.
Bearer tokens follow the ASCII `b64token` syntax in RFC 6750, excluding whitespace
and CR/LF.

**Plaintext HTTP accepts only `NoAuth` in 20B. There is no plaintext-auth opt-out.**
Disabling HTTPS certificate verification does not bypass that rule. SSH `NoAuth`
is unsupported; no SSH-agent, proxy or `.netrc` authentication is inferred.
Username/password on HTTPS is a data contract, not an implemented HTTP Basic or
vendor login strategy.

### Timeouts, identity and public output

`ConnectionTarget` requires `endpoint` and `authentication`. It also accepts
`connect_timeout=None` and `operation_timeout=None`, in seconds. `None` means no
Target override, never unlimited. Supplied values must be positive finite floats
or integers representable as a float; integers are explicitly converted.
Bools, zero, negatives, NaN, infinities, unsupported types and oversized integers
are rejected.

There are no invented operational defaults or RuntimeLimits ceilings here.
Future resolution must apply Action override, Target override, Profile default,
then Connector safe default, and the RuntimeLimits ceiling before execution.
A Connector must not blindly forward an unresolved `None` as an unlimited timeout.

All objects are frozen and slotted. Endpoints and descriptors compare their
fields as supplied; there is no semantic DNS/IP equivalence. Secret values,
credential-bearing authentication objects and Targets use identity equality and
identity hashing, not secret-content comparisons or connection-equivalence rules.
`NoAuth` is a stateless value.

`target.to_descriptor()` creates a separate `TargetDescriptor(scheme, host, port)`
using keyword arguments and the effective port. It contains only these three
fields, never a reference to the Target, auth or options. Its `to_dict()` returns
exactly those fields. It is credential-free, not anonymous: endpoint metadata can
still disclose internal topology.

### Secret boundaries and guarantees

`SecretValue(value, /)` accepts a nonempty string without conversion or trimming.
Its intended `repr` and `str` are fixed masked representations, independent of
length. Auth representations hide usernames, secret values and key paths; Target
representations do not expand authentication. Trust-file paths are also omitted
from endpoint representations.

`SecretValue.reveal()` deliberately returns the raw string for necessary local
contract validation and future Connector use. It is not an authorization mechanism
and must not be used for logging, public output or persistence.

Only `TargetDescriptor` and `CollectionResult` offer public `to_dict()` conversion.
Neither serializes credential-bearing objects. **Do not use or advertise
`dataclasses.asdict()`, `vars()`, pickle or reflective serializers as safe for
Targets, authentication or secret values.** Masked representation does not protect
reflection. Python introspection, debuggers, memory dumps, deliberate access to
private fields and copies of strings are outside this guarantee. Physical memory
zeroization is not promised.

Offline validation does not prove successful authentication, certificate or SSH
host-key verification, trusted file contents, effective timeouts, network
authorization, DNS rebinding protection or redirect safety. Future Connectors must
enforce trust, controlled origins/relative Action paths, runtime-auth ownership,
no implicit credentials/proxies, and secure failure when trust is unavailable.
There is no implemented `collect()`, Profile resolver, AuthStrategy, automatic
insecure-transport reporting or network operation in these contracts.

## Immutable results and provenance (20C)

The approved decisions are recorded in
[Issue #12](https://github.com/NipStack/nipstack-core/issues/12#issuecomment-6565483601).
20C added 16 public types and two JSON aliases, bringing both public export lists
to 30 entries at that increment. 20D adds four names, for 34 exports. These are
construction-time contracts, not an execution engine.

### Constructors and identities

The implemented constructor signatures are keyword-only:

```text
ProfileIdentity(*, profile_id: str, version: str | None = None)
SchemaIdentity(*, digest: str, algorithm: Literal["schema-c14n-v1"] = "schema-c14n-v1")
ExecutionMetadata(*, collection_id: str, nipstack_core_version: str,
                  started_at: datetime, finished_at: datetime, duration_ms: float,
                  correlation_id: str | None = None)
RawArtifact(*, artifact_id: str, action_id: str, kind: str, content_type: str,
            content: JSONValue, acquired_at: datetime, duration_ms: float)
NipStackCoreError(*, code: ErrorCode, stage: ErrorStage,
                 retry_hint: RetryHint = RetryHint.UNKNOWN,
                 context: Mapping[str, str | int] | None = None)
NipStackCoreDiagnostic(*, code: DiagnosticCode, stage: ErrorStage,
                      context: Mapping[str, str | int] | None = None)
FeatureResult(*, feature_id: str, status: FeatureStatus, scope_hint: ScopeHint,
              started_at: datetime, finished_at: datetime,
              schema_identity: SchemaIdentity | None = None,
              data: JSONDocument | None = None, error: NipStackCoreError | None = None,
              source_artifact_refs: Sequence[str] = ())
CollectionResult(*, status: CollectionStatus, profile: ProfileIdentity,
                 target: TargetDescriptor, execution: ExecutionMetadata,
                 features: Mapping[str, FeatureResult], artifacts: Mapping[str, RawArtifact],
                 error: NipStackCoreError | None = None,
                 diagnostics: Sequence[NipStackCoreDiagnostic] = ())
```

IDs, versions and correlation IDs are opaque nonempty strings, without
peripheral whitespace, control characters or Unicode surrogates. No UUID,
SemVer, registry membership or Profile resource convention is inferred.
`ProfileIdentity.version=None` preserves a requested ID before successful loading.
**Every nonempty Collection features mapping requires a known Profile version**,
including failed, skipped or cancelled results.

`SchemaIdentity` contains only the digest and algorithm. The digest must exactly
match `sha256:[0-9a-f]{64}`. The sole algorithm is `schema-c14n-v1`; its intended
input is JCS-canonicalized Schema content. Equal content can share an identity
across different Profiles and Features. Construction validates syntax, not the
digest's truth: computing/verifying the canonical digest belongs to 50D.

All timestamps must be timezone-aware UTC (zero-offset equivalents normalize to
UTC). Finish cannot precede start. `duration_ms` accepts finite nonnegative
integers/floats representable as a float, converts to float and rejects bool,
NaN, infinities and oversized integers. A supplied monotonic duration is not
recomputed or compared with wall-clock elapsed time. IDs, clocks and the
`nipstack_core_version` value must be supplied, not generated or read at runtime.

### JSON snapshots and observation shape

The aliases deliberately use explicit array types, not `Sequence`, so `str` is
not statically accepted as a JSON document root:

```python
from collections.abc import Mapping
from typing import TypeAlias

JSONValue: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | Mapping[str, "JSONValue"]
    | list["JSONValue"]
    | tuple["JSONValue", ...]
)
JSONDocument: TypeAlias = Mapping[str, JSONValue] | list[JSONValue] | tuple[JSONValue, ...]
```

Every supplied JSON container is recursively copied. Objects become read-only
mapping proxies backed by owned dictionaries; arrays become tuples. Strings and
keys must have valid Unicode scalar values; keys must be strings. Floating-point
numbers must be finite. Bytes, sets, dates, exceptions, secrets, auth objects and
other arbitrary Python objects are rejected without converting them to text.
Error messages do not echo keys, paths or values.

Cycles are rejected; shared acyclic subtrees are accepted and copied separately.
The exact limit is **64 containers along a path, including the root**; scalars
do not add depth. A 65th container fails explicitly, without truncation. This is
not a byte, width, CPU or memory budget and does not replace future RuntimeLimits.
Equality is ordinary Python structural equality, not JCS canonical equality.
There is no observation JSON Schema validation or universal vendor schema here.

### Artifacts and Feature results

`RawArtifact.kind` is an open semantic token matching ASCII `[a-z][a-z0-9_]*`,
such as `configuration_snapshot`, independent of text versus JSON.
`content_type` is nonempty single-line metadata without peripheral whitespace or
control/surrogate characters. It is descriptive, not parsed, sniffed or used to
decode/coerce content. Artifact and Action IDs are distinct roles, not derived
from command strings; equal strings are allowed.

An artifact represents **successful acquisition only**. `content` is required:
`None` means intentionally hidden, whereas `""`, `{}` and `[]` are legitimate
empty output. JSON scalar content is allowed. A visible JSON null cannot be
distinguished from hidden content in this contract. Failed acquisition creates
no artifact and must not be referenced.

`RawArtifactPolicy` has `NONE` and `PROFILE_DEFAULT`. It declares vocabulary only:
the future request field belongs to 20D, and actual exposure requires both the
Profile opt-in and caller `PROFILE_DEFAULT` in workstream 80. Instantiating this
enum does not filter or authorize disclosure of an artifact.

`FeatureStatus` has `SUCCESS`, `FAILED`, `SKIPPED`; `ScopeHint` has `SOURCE` and
`MANAGED_SYSTEM`. Scope is required. Feature IDs use the unchanged 20A grammar.

| Feature status | Data | Schema identity | Local error |
| --- | --- | --- | --- |
| `SUCCESS` | Object/array, including empty | Required | Forbidden |
| `FAILED` / `SKIPPED` | `None` | Optional (early failure) | Required |

Feature times describe processing, separately from artifact acquisition times.
Equal timestamps are valid, including for skipped Features. References normalize
to an ordered tuple; duplicates fail. A failed parse can retain references to
successfully acquired artifacts. Collection map keys must equal their contained
Feature/artifact IDs; every reference must resolve, including masked artifacts
whose metadata remains present. Unreferenced acquired artifacts are allowed.
This does not prove Action existence, at-most-once execution, Profile membership,
or detect duplicate dictionary keys overwritten before construction.

### Collection outcome

Status is explicit and checked, never inferred:

| Collection status | Required coherence |
| --- | --- |
| `SUCCESS` | Nonempty, all Features successful, no global error |
| `PARTIAL` | At least one success and one failed/skipped Feature, no global error |
| `FAILED` | A non-cancellation global error, **or** nonempty Features containing only local failures/skips and no global error |
| `CANCELLED` | Global `ErrorCode.CANCELLED`; any already-produced results may remain |

`FAILED(features={}, error=None)` is invalid. A global non-cancellation failure
can coexist with any mix of completed results, including all-success Features.
Global cancellation cannot use `FAILED`. Empty early failed/cancelled Collections
can have a known or unknown Profile version but require their global error.
Diagnostics never downgrade status and can accompany success.

Feature/artifact mappings are copied, frozen and retain insertion order; mapping
equality ignores order. Diagnostics normalize to an ordered tuple without
deduplication. The target must be an existing credential-free `TargetDescriptor`,
never a `ConnectionTarget`.

### Structured errors and bounded diagnostics

`NipStackCoreError` and `NipStackCoreDiagnostic` are result values, not raised
exceptions. Both expose a read-only fixed English `message` derived solely from
their code; no free-form message input or context interpolation is accepted.
Invalid construction still raises `NipStackCoreUsageError`, with native
`TypeError` for calls outside signatures.

`ErrorCode` contains exactly:

```text
PROFILE_NOT_FOUND PROFILE_INVALID SELECTION_INVALID TARGET_INVALID
FINGERPRINT_MISMATCH AUTHENTICATION_ERROR CONNECTION_TIMEOUT CONNECTION_ERROR
SESSION_SETUP_ERROR OPERATION_TIMEOUT RESOURCE_LIMIT_EXCEEDED COMMAND_ERROR
API_ERROR PARSE_ERROR SCHEMA_VALIDATION_ERROR DEPENDENCY_FAILED FEATURE_UNSUPPORTED
EXECUTION_CONTROL_ERROR CANCELLED CLEANUP_ERROR INTERNAL_ERROR
```

`ErrorStage` contains `PROFILE`, `PLANNING`, `CONNECTION`, `SESSION_SETUP`,
`FINGERPRINT`, `ACTION`, `PARSING`, `VALIDATION`, `CANCELLATION`, `CLEANUP`,
`INTERNAL`. There is no speculative code/stage compatibility matrix.
`RetryHint` is `NEVER`, `MAY_RETRY` or `UNKNOWN` (default), advisory only.
`DiagnosticCode` is separate: `CLEANUP_FAILED`, `EVENT_CALLBACK_FAILED`,
`INSECURE_TRANSPORT`. No exception translation or diagnostic generation occurs.
Every new enum is a standard `Enum` with uppercase string values equal to names;
20A's existing lowercase values remain unchanged.

Context is an owned read-only mapping, empty when input is `None`. It accepts
only these six named entries; unknown keys, nesting and arbitrary objects fail:

| Key | Accepted value |
| --- | --- |
| `action_id`, `connector_id` | ASCII `[A-Za-z0-9][A-Za-z0-9_.:-]*` |
| `feature_id` | The three-segment 20A grammar |
| `http_status` | Integer 100-599, not bool |
| `schema_keyword` | ASCII `[A-Za-z_$][A-Za-z0-9_$-]*`, including `$ref` |
| `cause_code` | Exactly an `ErrorCode.value` string, not an exception |

All context text is limited to 128 ASCII characters; nothing is dropped,
truncated, normalized or silently converted. These bounds are a predictable
technical metadata budget, not limits on primary Feature/Action IDs. New metadata
keys/limits can be introduced with reviewed validators, tests and documentation.
There is no arbitrary `extra` escape hatch; JSON paths are deferred because their
embedded property names can disclose sensitive content.

### Display, equality and remaining boundaries

All new values are frozen and slotted, with structural equality. Profile/schema
identities and execution metadata are hashable. Artifacts, Feature/Collection
results, errors and diagnostics are explicitly unhashable, even when empty.
The localized mypy assignment exceptions for `__hash__ = None` reflect Python's
unhashability sentinel versus the inherited callable annotation; runtime tests
verify both `hash()` rejection and `Hashable` exclusion.

Intended `repr`/`str` omit raw content, parsed data, contexts, opaque IDs and
correlation IDs; only technical kind/status/code/stage discriminants are shown.
Validation cannot recognize a secret deliberately disguised as a valid technical
token. Producers must select vetted metadata. Display protection is not
introspection, `dataclasses.asdict()`, pickle, serialization or debugger safety.
The 20D `CollectionResult.to_dict()` described below is the explicit result
conversion route. There is no generic reflective serializer or exporter.
Mapping proxies themselves are not directly serializable with `json.dumps()`.

20C does not add requests, execution controls/events, Profile loading, digest
computation, transport, parsers, schema validators, cancellation execution,
retries, persistence, runtime resource limits or `collect()`. Declared result
coherence does not prove that a future execution engine obeyed its lifecycle.

## Requests, control, events and result JSON (20D)

The approved decisions and definitive selection/integer clarifications are recorded in
[Issue #14](https://github.com/NipStack/nipstack-core/issues/14#issuecomment-6591437699).
The four additional exports are `CollectionRequest`, `ExecutionControl`,
`ExecutionEvent` and `EventKind`. All previous exports and constructor invariants
remain unchanged. Contract completion does **not** mean collection is executable:
`collect()` remains absent.

### Explicit one-target request

```text
CollectionRequest(*, profile_id: str, target: ConnectionTarget,
                  selection: FeatureSelection,
                  raw_artifact_policy: RawArtifactPolicy = RawArtifactPolicy.NONE,
                  correlation_id: str | None = None,
                  execution_control: ExecutionControl | None = None)
```

The request is frozen, slotted and keyword-only, with identity equality and
identity hashing. It requires a preconstructed `ConnectionTarget` and explicit
`FeatureSelection`. **`FeatureSelection.all()` is accepted when explicitly supplied;
omitting selection raises native `TypeError`, never an implicit ALL.**
Profile and correlation identifiers follow the same opaque-string conventions as
20C; no Profile lookup or Feature resolution occurs. Strings are not accepted in
place of Target, selection or policy types.

The optional control is retained verbatim, not inspected, copied, invoked,
displayed, compared or hashed. It is statically typed, not shape-validated at
runtime. The immutable envelope may therefore refer to a live caller-owned control.
Intended request `repr`/`str` show only the validated raw-policy discriminator;
they omit Target, selection, identifiers and control. No request `to_dict()`,
`to_json()` or other public serializer exists. Reflection is not credential-safe.

### Synchronous control interface

```python
from typing import Protocol

from nipstack_core import ExecutionEvent


class ExecutionControl(Protocol):
    def should_cancel(self) -> bool: ...

    def on_event(self, event: ExecutionEvent) -> None: ...
```

This structural interface is not `@runtime_checkable`, a concrete controller,
or an event dispatcher. It does not schedule tasks, create queues/threads,
poll cancellation or emit events. Runtime checking of attribute presence would
not establish callability, signatures, return types or safe behavior.

Workstream 80 must implement the already-defined failure semantics: an exception
from `should_cancel()` stops further acquisition with `EXECUTION_CONTROL_ERROR`;
an `on_event()` exception produces nonfatal `EVENT_CALLBACK_FAILED` and disables
later callbacks. These are **not implemented or verified runtime behaviors in
20D**. Cooperative cancellation cannot immediately interrupt arbitrary blocking
SSH/HTTP calls; future finite Connector timeouts remain necessary.

### Metadata-only observations

```text
ExecutionEvent(*, kind: EventKind, timestamp: datetime, collection_id: str,
               correlation_id: str | None = None, profile_id: str | None = None,
               action_id: str | None = None, feature_id: str | None = None,
               status: FeatureStatus | CollectionStatus | None = None,
               error_code: ErrorCode | None = None,
               duration_ms: float | None = None)
```

`EventKind` is a standard Enum whose values exactly equal these names:

```text
COLLECTION_STARTED PLAN_READY SESSION_OPENED FINGERPRINT_FINISHED
ACTION_STARTED ACTION_FINISHED SESSION_CLOSED FEATURE_STARTED
FEATURE_FINISHED COLLECTION_FINISHED
```

Events are frozen/slotted, structurally equal and hashable. Kind, timestamp and
collection ID are required. Timestamp follows the existing UTC-only convention;
optional duration follows the finite nonnegative millisecond rule. Neither time
nor identifiers are generated. Optional metadata may be absent, including on
terminal events. When supplied, `status` must be:

| Event kind | Supplied status |
| --- | --- |
| `FEATURE_FINISHED` | `FeatureStatus` |
| `COLLECTION_FINISHED` | `CollectionStatus` |
| Other kinds | Forbidden (`None` only) |

An `ACTION_FINISHED` may carry duration and an existing ErrorCode, not an invented
Action-status taxonomy. No full required-field transition matrix, lifecycle
proof or code/status compatibility matrix is imposed ahead of runtime work.
Opaque collection/correlation/Profile/Action IDs follow 20C text validation;
Feature IDs follow the 20A grammar when present. Primary IDs have no context-only
128-character limit.

No payload, raw output, complete FeatureData, credentials, headers, URLs,
commands, arbitrary context or free-form message fields exist. Producers must
use vetted technical IDs: syntax cannot recognize a secret or command deliberately
disguised as an ID. Intended display hides IDs and timing metadata, showing only
validated kind/status/error-code discriminants. There is no event serializer,
telemetry or logging-handler API.

### Explicit result conversion

```text
CollectionResult.to_dict(self) -> dict[str, JSONValue]
```

This is the sole new public conversion route. It explicitly traverses current
result fields, not arbitrary dataclasses or attributes. It returns fresh plain
dict/list containers, existing Enum `.value` strings, fixed microsecond UTC
timestamps (`YYYY-MM-DDTHH:MM:SS.ffffffZ`), and valid scalar values.
Use ordinary `json.dumps(result.to_dict())`, with no custom default or encoder.
There is no public `result_to_dict`, `to_json`, deserializer, format exporter,
raw-policy argument or persistence layer.

All meaningful keys are present, even when their value is null:

- Collection: `status`, `profile`, `target`, `execution`, `features`, `artifacts`,
  `error`, `diagnostics`.
- Profile: `profile_id`, `version`.
- Target: exactly `scheme`, `host`, `port`, via the existing credential-free
  `TargetDescriptor.to_dict()`.
- Execution: `collection_id`, **`nipstack_core_version`**, `started_at`,
  `finished_at`, `duration_ms`, `correlation_id`.
- Feature: `feature_id`, `status`, `scope_hint`, `started_at`, `finished_at`,
  `schema_identity`, `data`, `error`, `source_artifact_refs`.
- Schema identity: `digest`, `algorithm`, or null; no Profile/Feature fields.
- Artifact: `artifact_id`, `action_id`, `kind`, `content_type`, `content`,
  `acquired_at`, `duration_ms`.
- Error: `code`, `stage`, `retry_hint`, `context`, fixed `message`, or null.
- Diagnostic: `code`, `stage`, `context`, fixed `message`; no retry hint.

Features and artifacts remain ID-keyed objects; their insertion order is
preserved, as are array/reference/diagnostic orders. Repeated calls on the same
result are deterministic and independent, not views of frozen containers.
Changing the returned dictionaries/lists cannot change the result or a subsequent
conversion. Mapping equality does not promise identical bytes for independently
constructed values with different insertion orders. This is not JCS output.

The 64-container limit belongs to each 20C JSON payload, not to the entire output
envelope. It is not reapplied to the added Collection/Feature wrapper levels.
20C already rejects unsupported values, cycles, invalid Unicode, nonfinite floats
and invalid timestamps. Conversion does not recompute schema identity, reinterpret
status/provenance or perform Schema validation.

#### Standard JSON integer compatibility

20C's arbitrary Python integer acceptance is preserved. Conversion checks
integers using the standard JSON encoder under the **current interpreter
settings**. If an integer cannot be encoded, `to_dict()` raises
`NipStackCoreUsageError` with a fixed safe message, without echoing its value or
the containing key. It does not silently turn integers into strings, change
`sys.set_int_max_str_digits()`, truncate data or return a partial output.
Ordinary integers and large encodable integers remain integers.

Compatibility reflects settings at conversion time; changing interpreter settings
afterward can change later encoding behavior. Memory/CPU exhaustion and downstream
consumer numeric limits are separate concerns, not solved by this check. Future
RuntimeLimits must address resource budgets.

#### Exposure and credential boundary

Only the already-constructed CollectionResult and its credential-free descriptor
are traversed. No request, ConnectionTarget, auth or ExecutionControl is accessed;
`SecretValue.reveal()` is never invoked.

Hidden artifact content stays null; present raw content, empty strings/objects/
arrays and parsed FeatureData are preserved faithfully. The converter has no
Profile/request permission context and **does not enforce** raw double opt-in.
Workstream 80 must require both Profile `expose_by_default=true` and caller
`PROFILE_DEFAULT` before exposing raw in real collection results.

**The output may contain sensitive configurations, observations, topology, IDs
or technical context.** Credential-object exclusion and sanitized messages do
not provide general redaction or anonymization. Strings deliberately containing
secrets cannot be identified automatically while preserving legitimate data.
Producers/consumers own access, retention, redaction and storage policies.

### Complete synthetic JSON example

The following output corresponds to a valid PARTIAL result, with one successful
and one failed Feature referencing the same acquired, masked artifact. The digest
is the precalculated SHA-256 of the simple canonical synthetic schema
`{"type":"object"}`; conversion does not compute it.

```json
{
  "status": "PARTIAL",
  "profile": {
    "profile_id": "example.synthetic",
    "version": "1.0"
  },
  "target": {
    "scheme": "ssh",
    "host": "switch.example.invalid",
    "port": 22
  },
  "execution": {
    "collection_id": "demo-20d",
    "nipstack_core_version": "0.1.0",
    "started_at": "2026-11-02T00:00:00.000000Z",
    "finished_at": "2026-11-02T00:00:00.020000Z",
    "duration_ms": 20.0,
    "correlation_id": "demo-correlation"
  },
  "features": {
    "config.system.hostname": {
      "feature_id": "config.system.hostname",
      "status": "SUCCESS",
      "scope_hint": "SOURCE",
      "started_at": "2026-11-02T00:00:00.006000Z",
      "finished_at": "2026-11-02T00:00:00.007000Z",
      "schema_identity": {
        "digest": "sha256:a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
        "algorithm": "schema-c14n-v1"
      },
      "data": {
        "hostname": "edge-lab",
        "interfaces": [
          {
            "name": "Ethernet1",
            "addresses": [],
            "enabled": true
          }
        ],
        "note": null
      },
      "error": null,
      "source_artifact_refs": ["raw-1"]
    },
    "check.system.status": {
      "feature_id": "check.system.status",
      "status": "FAILED",
      "scope_hint": "SOURCE",
      "started_at": "2026-11-02T00:00:00.008000Z",
      "finished_at": "2026-11-02T00:00:00.009000Z",
      "schema_identity": null,
      "data": null,
      "error": {
        "code": "PARSE_ERROR",
        "stage": "PARSING",
        "retry_hint": "UNKNOWN",
        "context": {"action_id": "read_system"},
        "message": "Parse error."
      },
      "source_artifact_refs": ["raw-1"]
    }
  },
  "artifacts": {
    "raw-1": {
      "artifact_id": "raw-1",
      "action_id": "read_system",
      "kind": "configuration_snapshot",
      "content_type": "text/plain",
      "content": null,
      "acquired_at": "2026-11-02T00:00:00.005000Z",
      "duration_ms": 1.5
    }
  },
  "error": null,
  "diagnostics": [
    {
      "code": "CLEANUP_FAILED",
      "stage": "CLEANUP",
      "context": {"connector_id": "ssh", "cause_code": "CLEANUP_ERROR"},
      "message": "Cleanup failed."
    }
  ]
}
```

An early FAILED result can have `profile.version=null`, empty features/artifacts,
and a required global `PROFILE_NOT_FOUND` error. CANCELLED requires the global
`CANCELLED` error and may retain completed results. These are unchanged 20C
invariants, not serializers' inferences.

### Contract acceptance versus future execution

20A supplies explicit selection; 20B supplies offline target/auth data and safe
descriptor projection; 20C supplies immutable provenance/results/errors; 20D
composes requests, control/event data and explicit JSON result conversion.
Unit, type and installed-wheel tests exercise these contracts offline.

No collection engine, Profile loading, Connector/Session, runtime event
production, callback execution, cancellation, raw filtering, automatic retry,
JCS calculation, Schema validation, persistence or exporter is supplied. The
public `collect(request) -> CollectionResult` remains a future API, not an
implemented placeholder.
