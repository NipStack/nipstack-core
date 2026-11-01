# Public contracts

Public contracts are exported from both `nipstack_core` and
`nipstack_core.contracts` and depend only on the standard library. They cover
explicit Feature selection and offline connection-target data. The accepted
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

Only `TargetDescriptor` offers public serialization. **Do not use or advertise
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
There is no implemented `collect()`, Profile resolver, AuthStrategy, operational
insecure-transport diagnostic or network operation in these contracts.
