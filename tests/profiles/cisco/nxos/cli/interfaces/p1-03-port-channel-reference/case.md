# P1-03 — p1-03-port-channel-reference

- **Status:** `A5_APPROVED` / `PUBLICATION_AUTHORIZED` for this synthetic case; Git actions require separate approval.
- **Input classification:** synthetic reconstruction guided by privately inspected command shapes; no source content copied verbatim.
- **Goal:** A Port-Channel declaration plus two Ethernet membership references; no implicit joins.
- **Origin category:** synthetic; private-source functional research, details withheld from public files.
- **Functional basis:** Port-Channel and channel-group patterns observed in private NX-OS 9K configs; IDs and descriptions synthesized; release-specific validity of the mode token is not established by this synthetic case.
- **Oracle rationale / open question:** Mixed output is an experimental oracle only. Future Ethernet/Port-Channel Features may have independent template outputs using the same Action/Artifact. Keep `channel_group` as an explicit integer reference, not a resolved join or proof of operational aggregation.
- **Review limits:** the experimental oracle is approved; actual NX-OS release compatibility and Native parsing remain unverified.
- **Scope:** no parser implementation, no claimed official Feature or platform support.
