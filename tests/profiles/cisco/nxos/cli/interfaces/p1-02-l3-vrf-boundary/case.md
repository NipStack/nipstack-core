# P1-02 — p1-02-l3-vrf-boundary

- **Status:** `A5_APPROVED` / `PUBLICATION_AUTHORIZED` for this synthetic case; Git actions require separate approval.
- **Input classification:** synthetic reconstruction guided by privately inspected command shapes; no source content copied verbatim.
- **Goal:** A routed Ethernet interface with VRF and IP, followed by a minimal adjacent interface; prevent field bleed.
- **Origin category:** synthetic; private-source functional research, details withheld from public files.
- **Functional basis:** VRF membership and IP syntax observed together in private NX-OS 9K/7K Ethernet interface blocks; values regenerated.
- **Oracle rationale / open question:** Preserve VRF and IPv4 address as strings exactly as captured. Do not infer operational status or inherit attributes to the adjacent minimal Ethernet record.
- **Review limits:** the experimental oracle is approved; actual NX-OS release compatibility and Native parsing remain unverified.
- **Scope:** no parser implementation, no claimed official Feature or platform support.
