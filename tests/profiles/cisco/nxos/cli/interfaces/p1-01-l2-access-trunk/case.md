# P1-01 — p1-01-l2-access-trunk

- **Status:** `A5_APPROVED` / `PUBLICATION_AUTHORIZED` for this synthetic case; Git actions require separate approval.
- **Input classification:** synthetic reconstruction guided by privately inspected command shapes; no source content copied verbatim.
- **Goal:** Two contiguous Ethernet blocks with access VLAN and explicit trunk mode; description omitted in second.
- **Origin category:** synthetic; private-source functional research, details withheld from public files.
- **Functional basis:** Access/trunk syntax observed in a private NX-OS 5K config; examples recomposed from distinct observed structures, not a verbatim contiguous original passage.
- **Oracle rationale / open question:** Do not infer access mode or operational status; preserve only explicitly declared fields. VLAN ID is an integer, comma-separated allowed VLANs are an ordered list of integers; ranges/override syntax not exercised.
- **Review limits:** the experimental oracle is approved; actual NX-OS release compatibility and Native parsing remain unverified.
- **Scope:** no parser implementation, no claimed official Feature or platform support.
