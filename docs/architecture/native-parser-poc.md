# NipStack Native — corpus-led proof-of-capability protocol (40A)

> **Status:** `A5_APPROVED` / `PUBLICATION_AUTHORIZED`. The owner authorizes publication of the 26 synthetic 40A files, including their inclusion in the sdist. No release, Profile activation or parser implementation is implied. Staging, commit, push and PR still require separate owner approval.

## Purpose and architectural boundaries

NipStack Native is the V1 declarative parser for CLI/text network data. The corpus tests **observable extraction behaviors**, not an NX-OS-specific parser and not the final organization of vendor Profiles. The other V1 parser engine is JMESPath for JSON/API data; no TTP parser, templates, runtime adapter or fallback is introduced.

The conceptual parser boundary is an explicitly supplied mapping of Action IDs to immutable `RawArtifact`s plus a prepared parser definition producing `FeatureData`. The exact internal API and Native template grammar remain **open until evidence-led 40B design**. `FeatureData` is the output passed unchanged for subsequent independent Observation Schema validation. The root of `FeatureData` is a JSON object or array; malformed parsing must never be disguised as `{}` or `[]`.

Several future Features may reuse one acquired Action/Artifact and interpret it independently through different declarative template resources. An Ethernet template, a Port-Channel template and a static-route template need not share a mixed output or mutable parser state. A block of an unselected kind can still delimit selected blocks. Parser invocation does not acquire network data, read arbitrary files, invoke other templates, or mutate inputs.

## Evidence inventory and scenario map

Fixture location: `tests/profiles/cisco/nxos/cli/`; each case supplies `input.txt`, `expected.json`, `case.md`.

| Family | Requirement specified by the corpus | Not proved |
| --- | --- | --- |
| P0-01 | Select the NXOS line within Software and capture only version token | Arbitrary suffix grammar |
| P0-02 | Select mandatory system line rather than distinct kickstart or BIOS version | Fallback selection |
| P1-01 | Repeat Ethernet records, optional fields and explicit VLAN typed captures | VLAN ranges or every switchport variation |
| P1-02 | Close previous interface context and preserve routed-interface attributes | Operational status from config |
| P1-03 | Preserve channel-group reference and multiple interface types | Join or resolved Port-Channel membership |
| P1-04 | Ignore Port-Channel output while letting it close a selected Ethernet record | Production Feature definitions |
| P2-02 | Repeat routes under distinct VRF parents, preserve duplicate prefix in distinct contexts, end scope at unrelated top-level section | Global routes outside a VRF |
| P2-03 | Recognize three explicitly demonstrated route destination forms and optional typed fields | Arbitrary route attribute permutations |

These fixtures are **synthetic reconstructions**, not certified device-output captures. The corpus specifies what capabilities a future parser *would need* to satisfy the chosen oracles; it does **not** prove that an engine currently implements those capabilities, nor that all combinations are valid on every NX-OS release.

## Oracle rules

1. Review each `expected.json` independently of the parser or any historical parser output; justify each field against the example input.
2. Explicitly preserve input order, occurrences and types. Omitted field ≠ `null` ≠ `""` ≠ `false` ≠ an invalid extraction.
3. No automatic schema-driven massaging, dict/list wrapping, field pruning, access-mode inference, status inference, global normalization or route deduplication.
4. Numeric conversion is allowed only when selected in the template/contract. String version, interface, address, prefix and VRF values must not be secretly normalized.
5. A missing required singleton capture, a malformed or ambiguous targeted capture, or an unrecognized suffix yields a sanitized failure, not silent first/last-wins or fallback. An absent optional capture remains omitted. Unrelated lines may be skipped if their block/section delimiters are still observed.
6. EOF is a valid delimiter for a known complete input, but is not proof that an upstream command or transport was not truncated.
7. Oracle comparison must be type-sensitive (avoid Python's `True == 1` trap) and order-sensitive for JSON arrays unless a future explicit contract says otherwise.

## Minimal data-only Native capability candidates — not frozen DSL syntax

- A bounded, explicit section/record start/end policy, including boundaries encountered in unselected record categories.
- Per-line matching and named capture to extract labels/tokens/strings without admitting arbitrary executable code.
- Required/optional captures, cardinality validation, and deterministic handling of duplicates.
- Repeated records with local state and ordered output; strict decimal and bounded separated-value conversions where required.
- Explicit finite alternatives and parent-to-child context for VRF routes (later, if supported by evidence).

**Non-goals** at this stage: TTP compatibility, general-purpose regex execution without a safety policy, recursive network AST, arbitrary Python, joins/merges, multi-input, source discovery, active ProfileRegistry, Connector and `collect()`.

## Increment boundaries

- **40A:** accept/select/redact/create experimental samples, independently review oracles, record uncovered cases and publication requirements. No parser implementation.
- **40B:** first prove both P0 forms and at least one small P1 repeated-interface/boundary case using a minimal, pure engine; establish explicit compile-versus-run separation without freezing a full DSL.
- **40C:** expand P1 and prove parent VRF/child routes and route alternatives P2 only as justified by approved fixtures. Complex joins remain deferred.
- **40D:** report correctness, coverage, repeated-run determinism, failure cases, and reproducible compile/runtime CPU and peak-memory measurements; document integrations needed by workstream 50.

## Verification and scorecard method

- 40A validates fixture inventory, UTF-8, strict JSON syntax (including duplicate key/nonfinite rejection), root object/array, and independently reviewed network semantics. No test that returns the oracle as a fake parser counts as engine evidence.
- Future golden tests compare exact actual `FeatureData` with approved expected values (JSON types, order and missing keys) and include negative and adjacent-block fixtures.
- Parsing and compile/preparation are separately measured with pinned Python/OS/CPU/commit and versioned test data; report method, runs, dispersion and peak-memory method without unsupported performance claims.
- Report scenarios as **PASS / FAIL / NOT_RUN / NOT_VERIFIED**, disclose unsupported structures explicitly, and prevent raw payloads/secrets from entering error strings or logs.
- Input size, per-line size, number of records/captures and matching complexity must be bounded in the engine; loader resource limits alone do not cover parser runtime behavior.

## Provenance, reuse and review

Current files are authored synthetic demonstrations. Original private configurations and prior templates are not dependencies and must not be copied into public files. Do not publish sensitive values, source paths, internal names, customer identifiers, raw source snippets or unauthorized copyrighted material. The owner has approved publication of these 26 reviewed synthetic files, including their inclusion in the sdist; this approval does not cover real configurations, historical TTP templates or other private data. Actual NX-OS compatibility remains unverified, and no Native parser or benchmark result is available.

The experimental oracles and publication scope are approved. The final repository commit and 40B implementation still require explicit separate owner authorization. Nothing in this 40A specification confers permission to stage, commit, push, open a PR or activate a Profile.
