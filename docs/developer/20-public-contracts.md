# Public contracts

The public contracts currently implemented are `FeatureSelection`,
`FeatureSelectionKind`, and `NipStackCoreUsageError`. They are exported from both
`nipstack_core` and `nipstack_core.contracts` and depend only on the standard
library. The accepted initial contract is recorded in
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

These are selection contracts only: there is no implemented `collect()` API,
Profile resolver, or network operation in this increment.
