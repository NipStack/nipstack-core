# P0-02 — p0-02-n7k-software

- **Status:** `A5_APPROVED` / `PUBLICATION_AUTHORIZED` for this synthetic case; Git actions require separate approval.
- **Input classification:** synthetic reconstruction guided by privately inspected command shapes; no source content copied verbatim.
- **Goal:** Choose system: version among BIOS/kickstart/system labels, while preserving spacing.
- **Origin category:** synthetic; private-source functional research, details withheld from public files.
- **Functional basis:** Observed label variation in a private NX-OS 7K show version; all identifiers/versions are synthetic.
- **Oracle rationale / open question:** Choose mandatory `system` version (`7.3(2)D1(1)`), never fallback to `kickstart` (`7.3(1)D1(1)`). Deliberately different synthetic values make incorrect label selection detectable. Duplicate/missing system must fail instead of selecting arbitrary alternatives.
- **Review limits:** the experimental oracle is approved; actual NX-OS release compatibility and Native parsing remain unverified.
- **Scope:** no parser implementation, no claimed official Feature or platform support.
