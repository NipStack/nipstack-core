# P2-03 — p2-03-route-form-alternatives

- **Status:** `A5_APPROVED` / `PUBLICATION_AUTHORIZED` for this synthetic case; Git actions require separate approval.
- **Input classification:** synthetic reconstruction guided by privately inspected command shapes; no source content copied verbatim.
- **Goal:** Alternative route destinations: Null0, next-hop, interface + next-hop; optional name/tag/track.
- **Origin category:** synthetic; private-source functional research, details withheld from public files.
- **Functional basis:** Distinct route grammar patterns observed in a private NX-OS 7K config; synthetic redaction/reconstruction, not a literal extract.
- **Oracle rationale / open question:** Optional keys omitted when absent; `Null0` is an explicit interface rather than an IP next-hop. Tag/track are integers. Unknown suffix/attribute combinations are not assumed supported by these three forms.
- **Review limits:** the experimental oracle is approved; actual NX-OS release compatibility and Native parsing remain unverified.
- **Scope:** no parser implementation, no claimed official Feature or platform support.
