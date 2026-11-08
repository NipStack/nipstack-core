# P1-04 — Ethernet-only projection across an intervening Port-Channel

- **Status:** `A5_APPROVED` / `PUBLICATION_AUTHORIZED` for this synthetic case; Git actions require separate approval.
- **Input classification:** fully synthetic network CLI scenario, inspired by observed command categories but not claimed as a verbatim real-device sequence.
- **Goal:** two Ethernet records with an intervening Port-Channel section; the Port-Channel must close the first Ethernet block despite not being selected for Ethernet output.
- **Expected projection:** exactly two Ethernet records, in input order; Port-Channel data must not leak or be emitted by the Ethernet-only projection.
- **Future Profile implication:** a separate Port-Channel Feature/template may parse the same acquired text independently; this fixture does not require joined output or shared mutable parser state.
- **Review limits:** the scenario demonstrates a block-boundary requirement for a synthetic text; it does not establish compatibility across NX-OS versions or implement an engine.
- **No parser code, runtime feature or official Profile is delivered. Publication authorization covers this synthetic case only, not private source material or implementation work.**
