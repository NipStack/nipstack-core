# P2-02 — p2-02-two-vrf-sections

- **Status:** `A5_APPROVED` / `PUBLICATION_AUTHORIZED` for this synthetic case; Git actions require separate approval.
- **Input classification:** synthetic reconstruction guided by privately inspected command shapes; no source content copied verbatim.
- **Goal:** Two VRF sections containing two routes each, an identical prefix in both VRFs, and a final unrelated top-level interface; prevent route deduplication and parent-context leakage.
- **Origin category:** synthetic; private-source functional research, details withheld from public files.
- **Functional basis:** Indented ip route commands under vrf context observed in private NX-OS 9K/7K configs; values reconstructed using documentation ranges.
- **Oracle rationale / open question:** Approved experimental shape: flat ordered array; VRF copied from its enclosing section; two routes per VRF; no merge/deduplication, no automatic defaults. `interface Ethernet1/10` closes VRF scope and emits no route.
- **Repeated-record limitation:** repeated prefixes in distinct VRFs do not demonstrate preservation of two strictly identical records; this case contains no such duplicate records.
- **Boundary limitation:** the transition to an unrelated top-level interface is present in the input, but correct VRF-context closure by a Native engine remains to be demonstrated in later tests.
- **Review limits:** the experimental oracle is approved; actual NX-OS release compatibility and Native parsing remain unverified.
- **Scope:** no parser implementation, no claimed official Feature or platform support.
