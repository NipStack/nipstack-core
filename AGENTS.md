# NipStack Core — Repository Agent Instructions

## Purpose and source of truth

NipStack Core is an independent, open-source Python library for collecting network observations and turning them into traceable, validated, structured data. It supports standalone Python and CLI use and can be integrated by other applications without depending on them.

These instructions apply to AI coding agents working in this public repository. All implementation and review requirements must be understandable from files in this repository. Public architecture documents and accepted ADRs, when present, are authoritative for detailed behavior. If a required specification has not yet been published here, identify the gap and propose a public design/ADR rather than assuming undocumented requirements.

## V1 architectural commitments

- Main API: synchronous `collect(CollectionRequest) -> CollectionResult`.
- Keep public contracts small, typed, stable, and independent of third-party transport/parser types.
- Separate `contracts`, `profiles`, `catalog`, `planning`, `execution`, `connectors`, `parsers`, `validation`, `exporters`, and `cli`.
- Catalog and execution share the same validated ProfileRegistry; Catalog is read-only.
- Planning is deterministic, immutable, and free of network I/O.
- Connectors manage transport and Session lifecycle; parsers transform data locally; validation checks Observation Schemas separately.
- Feature selection is explicit; required Actions are deduplicated; collection happens before local parsing and validation.
- A Collection targets one logical network target. Do not add hidden concurrency, automatic retries, undocumented fallbacks, application persistence, or mutable state shared across Collections.
- Preserve RawArtifact provenance, partial results, structured errors, and the difference between empty and failed observations.

## Parsing and Profiles

- V1 has exactly two parser engines: **`native` for CLI/text** (NipStack Native) and **`jmespath` for JSON/API**.
- TTP is **not supported in V1**: no dependency, adapter, executable templates, compatibility layer, or fallback.
- Parsing is selected per Feature through ParserRegistry.
- NipStack Native templates must be declarative, deterministic, data-only, and developed incrementally from real network cases; do not invent an oversized general-purpose DSL.
- Do not execute arbitrary Python, imports, `eval`, or `exec` from Profile resources.
- Profiles are self-contained and versioned, with a `profile.yaml` manifest; keep Actions, Features, parser resources and Observation Schemas distinct.
- Validate Profiles and parser resources offline before network I/O.
- Observation Schemas use JSON Schema Draft 2020-12; their root is an object or array. Do not enforce one universal cross-vendor schema or perform implicit output-shape normalization.

## Safety and reliability

- Assume all network output and external Profile resources are untrusted.
- Require secure TLS and SSH host-key verification by default; enforce timeouts, resource budgets, path confinement and explicit failures.
- Never commit, log, or persist secrets or raw sensitive device configurations.
- Never contact a real network device without explicit user authorization.

## Development and verification

- Python >=3.11; initial development interpreter Python 3.12. Distribution/repository: `nipstack-core`; importable Python package: `nipstack_core` under `src/nipstack_core/`.
- Use `pyproject.toml`, Hatchling, `uv`/`uv.lock` for development and CI, Ruff, mypy, pytest, and `py.typed`.
- Keep standard tests deterministic and offline; use FakeConnectors, sanitized network fixtures and golden tests.
- When the toolchain exists, run relevant formatting, lint, type, test and packaging checks. Report what actually ran and what did not.
- Keep work focused: propose a plan for substantial changes; explain public contract impacts; do not add unrelated dependencies or features.
- Use short-lived branches and Pull Requests into protected `main`, with Conventional Commits-style titles and squash merge. Do not commit, push, merge, tag, or release without authorization.
- Keep public documentation updated alongside changes. Missing public architecture or contributor guidance is a documentation task, not a reason to assume hidden specifications.

## Scope-specific instructions

Additional `AGENTS.md` files in subdirectories add guidance for their respective files. Follow the root commitments as well.
