# P0-01 — p0-01-n9k-software

- **Status:** `A5_APPROVED` / `PUBLICATION_AUTHORIZED` for this synthetic case; Git actions require separate approval.
- **Input classification:** synthetic reconstruction guided by privately inspected command shapes; no source content copied verbatim.
- **Goal:** Find NXOS version, not BIOS version; stop at Hardware.
- **Origin category:** synthetic; private-source functional research, details withheld from public files.
- **Functional basis:** Observed header-and-label pattern in a private NX-OS 9K show version; values and context recreated synthetically.
- **Oracle rationale / open question:** Capture only the NXOS version token; the deliberately present synthetic `[build LAB]` annotation is excluded by an explicit, bounded pattern, not by general fallback/normalization. Unknown targeted suffixes are future negative cases; no SemVer coercion.
- **Review limits:** the experimental oracle is approved; actual NX-OS release compatibility and Native parsing remain unverified.
- **Scope:** no parser implementation, no claimed official Feature or platform support.
