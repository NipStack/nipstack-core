# NipStack Native — Parser Development Guidance

This file supplements the root and Python package `AGENTS.md` instructions.

## Scope

NipStack Native is the only V1 CLI/text parsing engine. JMESPath owns JSON/API transformations. Do not introduce TTP or another CLI parsing dependency, adapter or fallback.

## Design

- Preserve the common parser contract: inputs are RawArtifacts and output is exactly the FeatureData validated by a separate Observation Schema validator.
- Keep parser behavior pure and deterministic: no network, filesystem side effects, global mutable state, secret lookup, clock-dependent output, or mutation of RawArtifacts.
- Templates are declarative and data-only. Never permit arbitrary Python, scripts, imports, callbacks, `eval`, or `exec`.
- Add only primitives supported by demonstrated network requirements. Candidate primitives include hierarchical blocks, nested/repeating sections, optional lines, syntax alternatives, typed captures, presence booleans, lists/split, controlled conversions, block boundaries, merge/group-by-key and join-by-key.
- The native template DSL syntax is not fixed in advance. Propose and test each new syntax and its validation rules against real representative fixtures before standardizing it.
- Do not hardcode vendor-specific grammars in the generic parser engine; keep those in Profile resources.
- Do not silently normalize dicts to lists, prune empty values, remove wrappers or invent observations; distinguish absent, empty and failed states.
- Validate/compile native templates at Profile load when feasible; reject unsupported, unsafe and ambiguous constructs explicitly.

## Evidence and quality

- Begin with representative NX-OS interface/routing examples, then extend to FortiGate IPsec, PAN-OS or F5 when justified.
- Add golden fixtures and malformed/edge-case tests for each primitive, including deterministic result and error contracts.
- Evaluate correctness, coverage, readability and maintainability of templates as well as CPU and peak memory before broad Profile expansion.
- Treat superior capability or performance compared with alternatives as a testable objective, never as an assumed result.
