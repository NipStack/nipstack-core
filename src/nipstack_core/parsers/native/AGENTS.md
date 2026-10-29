# NipStack Native — Parser Development Guidance

This file supplements the root and Python package `AGENTS.md` instructions.

## Scope and design

- NipStack Native is the **only** V1 CLI/text parser. JMESPath owns JSON/API transformations. No TTP engine, templates, dependency, adapter, compatibility layer, or fallback.
- Inputs are validated/prepared resources and RawArtifacts; output is exactly the FeatureData validated independently against its Observation Schema. Keep transformations pure and deterministic: no network access, arbitrary file access, global mutable state, secret lookup, clock-dependent output, or RawArtifact mutation.
- Templates are declarative and data-only. Reject arbitrary Python, scripts, imports, callbacks, `eval`, and `exec`.
- Introduce only primitives justified by distinct real requirements. Possible areas include nested/repeating blocks, optional lines, alternatives, typed captures, presence flags, list/split, controlled conversions, block boundaries, and explicit grouping/joining. These are **candidates**, not a pre-approved DSL feature list.
- Propose and test syntax, validation, error behavior, and resource limits before freezing any DSL rule. Do not hardcode vendor-specific grammar in the generic engine.
- Do not silently normalize dictionaries/lists, prune empty values, discard wrappers, or invent observations. Distinguish absent, valid empty, and failed results.
- Validate/compile templates during offline Profile preparation when feasible; fail explicitly on unsupported, unsafe, or ambiguous constructs.

## Evidence-driven implementation order

- **P0 — NX-OS `show version`:** first compact CLI proof and intended initial official SSH Feature (`check.global.show_version`), subject to the selected increment's approved Profile/Schema contract.
- **P1 — interfaces** and **P2 — static routes:** representative distinct-complexity parsing scenarios used to prove and qualify Native; **not automatically official V1 Features**. Broader vendor cases (Fortinet, PAN-OS, F5, etc.) require their own approved scope.
- Prefer **small, meaningfully different CLI excerpts**, not complete running configurations or hundreds of repetitive interfaces. Verify provenance, rights, coherent sanitization, and publication approval before any real-source fixture enters the public repository. Historical `ndcore` templates are reference material, **not** executable compatibility assets and not required context for public contributors.
- Add golden expected outputs and malformed/edge-case tests for each implemented primitive. Measure correctness, coverage, template readability, CPU, and peak memory under a reproducible offline methodology; never assert performance superiority without evidence.
- Preserve explicit boundaries between **parser capability demonstrated**, **official bundled Feature**, and **authorized real-device lab proof**. A parser test passing is not proof of vendor-wide support or G3-SSH.
