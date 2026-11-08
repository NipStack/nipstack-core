# NipStack Native — 40A / A5 approved experimental corpus

**Status: `A5_APPROVED` · `SYNTHETIC_RECONSTRUCTION` · `PUBLICATION_AUTHORIZED`.**

These compact fixtures are synthetic, based on the categories of CLI syntax identified during authorized private research, **not verbatim excerpts** of live device configurations. All identifiers and addresses are invented (IP examples use documentation address ranges). They are **not evidence of compatibility with any particular NX-OS release**, nor proof that all simulated combinations occur on one device. No historical TTP templates are included.

The owner has approved the A5 **design decisions, three corpus corrections and final technical review**, and authorized publication of these 26 synthetic files, including their inclusion in the NipStack Core sdist. This authorization does not cover real configurations, historical TTP templates or other private data. The `expected.json` files express independently authored, approved experimental oracles; they are not generated from a Native implementation (no Native implementation exists yet). Staging, commit, push and PR remain subject to a separate approval of the final local preparation.

## Inventory

| Case | Focus | Scope |
| --- | --- | --- |
| P0-01 | NXOS versus BIOS, Software/Hardware sections, annotated version token | P0 |
| P0-02 | `system` versus different `kickstart` and BIOS values | P0 |
| P1-01 | Access/trunk Ethernet records, optional description and typed VLANs | P1 |
| P1-02 | L3/VRF Ethernet and adjacent minimal Ethernet boundary | P1 |
| P1-03 | Mixed Port-Channel/Ethernet records with explicit membership references | P1 experimental (not a production Feature shape) |
| **P1-04** | Ethernet → Port-Channel → Ethernet: unselected section still closes prior record | P1 boundary test |
| **P2-02** | Two VRFs, two routes each, shared prefix, boundary to unrelated interface | P2 |
| P2-03 | Route forms: `Null0`, next-hop, interface plus next-hop, `tag` and `track` | P2 |
| P2-01 (not included) | Global route outside VRF | **NOT_VERIFIED** in the examined reference sources |

## Oracle decisions approved for the experimental design

- `FeatureData` is exactly the parser output, rooted at an object (P0) or array (P1/P2). No global normalization or implicit enrichment.
- Missing fields are omitted; valid empty values are not fabricated; parser errors must not be represented as empty output.
- Preserve source order and duplicates when explicitly observed; no join, merge, sorting, or deduplication by default.
- P0 captures the **specific label**: NXOS (P0-01) or system (P0-02), not the first apparent version or automatic fallback. P0-01 captures the token only; any allowable suffix must be explicitly recognized.
- Typed captures are explicit: VLAN/group/tag/track numeric IDs are integers where present; comma-separated VLAN values are an ordered integer list. Versions, VRFs, descriptions, interface names, prefixes and addresses remain strings unless separately approved.
- Do not infer interface operational state from `no shutdown`, or infer `switchport_mode=access` merely from an access-VLAN declaration.
- Different interface types can use **independent future Profile Feature templates** on the same immutable acquisition. P1-03's mixed result is experimental; P1-04 demonstrates an Ethernet-only projection even when Port-Channel closes the active block.
- P2 routes use a flat, ordered array with explicit VRF context; unrelated top-level sections end that context. Global routes are not covered.
- A malformed targeted line, duplicate singleton capture, or unsupported suffix must not be silently accepted; unrelated lines outside projection may be ignored when section boundaries remain correctly enforced.

## Experimental delivery boundaries

- **40A:** corpus, exact expectations, evaluation protocol and review; **no parser, DSL, active Registry, official Profiles or network I/O**.
- **40B:** start with P0 (section/line/token), then prove **at least one minimal P1 repeating-block case** with explicit boundaries before declaring 40B complete.
- **40C:** broaden P1 as evidenced, then VRF parent/child and alternative routes from P2; no premature joins or generic AST.
- **40D:** measure exactness, failures, reproducibility, CPU/memory, maintainability; hand off only tested capability contracts to workstream 50.

## Approved publication scope and remaining gates

1. The owner has accepted the final technical review of the exact synthetic inputs and oracles, including the **three A5 corrections**, and authorized their publication. This does not certify syntax fidelity to any actual NX-OS release.
2. Test the curated JSON documents as strict JSON (no duplicate keys, non-finite values or invalid roots). Later golden tests must compare JSON types strictly (`true` and `1` must not compare as equal).
3. Keep fixture-specific limitations explicit. Add targeted negative variants in 40B/40C; no fake parser returning `expected.json`.
4. Publication authorization covers only these 26 reviewed synthetic files. Verify licensing/reuse and review any additional future content, including metadata. **Private-source access or synthetic reconstruction alone is not an automatic publication license.**
5. Human-review the final local corrections and explicitly authorize staging, commit, push and PR. **Content publication authorization does not authorize GitHub changes.**

## Known experimental gaps

- No top-level P2-01 global route; no claim of global-route coverage.
- No generic range VLAN handling (`1-10`, `all`, `add/remove`), no arbitrary permutations of route attributes, no multi-input or joins.
- No comprehensive malformed/empty/large input suite, no CRLF/tab variants, no perf benchmarks and no parser implementation.
- End-of-file may close a complete block; EOF alone cannot certify that a transport did not truncate the source.
