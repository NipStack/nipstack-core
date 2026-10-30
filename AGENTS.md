# NipStack Core — Repository Agent Instructions

## Purpose, scope, and sources of truth

NipStack Core is an independent, open-source Python library for network data collection, parsing, and traceable structured observations. It supports standalone Python and CLI use and has no dependency on NipStack Center.

These instructions apply to all coding agents (GitHub Copilot, Codex, Claude Code, or others) and human contributors. Follow this file and all applicable, more specific `AGENTS.md` files. Do not assume an agent automatically discovers every instruction file: explicitly read the relevant files before starting a task.

The public repository is self-contained. The assigned GitHub Issue, accepted public contracts, code, tests, documentation, and ADRs define the task and implemented behavior. Never require access to private `NipStack_Docs`, historical repositories, or chat history. If a requirement is missing or contradictory, flag it and request a decision rather than inventing a contract. A proposal or workstream plan does not by itself authorize a public API or code change.

**Before analyzing or changing code**, read [CONTRIBUTING.md](CONTRIBUTING.md) and [the public coding standards](docs/developer/coding-standards.md). These are the permanent contribution and maintainability rules for both agents and humans; do not duplicate them in scoped `AGENTS.md` files.

## Issue-driven, agent-agnostic workflow

1. Work on **one bounded increment** at a time (for example, `20A`, `20B`, or `40A`) from a self-contained public GitHub Issue. Preserve the workstream numbering **20–140**; do not reinterpret an entire workstream as one coding task.
2. **Analysis pass — no changes:** read the Issue, applicable `AGENTS.md`, existing code/tests, and public references; propose scope, file/API changes, alternatives, risks, tests, dependencies, and verification commands. Identify choices requiring human approval.
3. **Implementation pass — only after explicit approval:** implement the approved increment on a short-lived branch. Add focused tests and only the durable documentation needed. Do not silently expand scope or introduce dependencies, new public APIs, or compatibility behavior.
4. Prepare a focused Pull Request linked to its Issue, with actual check results, limitations, and unresolved items. Respect protected `main`, required CI, review, and squash-merge rules. Do not commit, push, merge, tag, or release without authorization.
5. Keep transient task briefs, agent prompts, and session plans in the Issue/PR conversation; do not add permanent vendor-specific prompts to the repository by default.

## V1 architectural commitments

- Main public API: synchronous `collect(CollectionRequest) -> CollectionResult` for **one logical network target**. Do not add a placeholder `collect()` merely to make an unfinished API appear available.
- Keep public contracts small, typed, and independent of transport/parser third-party types. Maintain distinct `contracts`, `profiles`, `catalog`, `planning`, `execution`, `connectors`, `parsers`, `validation`, `exporters`, and `cli` responsibilities.
- Catalog and collection use the same **validated, immutable ProfileRegistry**; Catalog is read-only. Execution planning is pure, deterministic, and immutable.
- A Collection uses one isolated Session; execute required Actions sequentially, acquiring each Action ID at most once. Resolve explicit Feature selections without implicitly selecting all Features.
- Connectors own network transport, authentication boundaries, and Session lifecycle; parsers transform locally; JSON Schema validation is a separate concern.
- Preserve RawArtifact provenance, legitimate empty observations, partial results, structured sanitized errors, and explicit cancellation behavior.
- V1 requires both **SSH/CLI/Native** and **HTTP/JSON/JMESPath** paths, each with one minimal official Feature. Do not expand official Feature coverage merely because parsing test cases exist. No hidden parallelism, automatic retry, fallback, application persistence, or cross-Collection mutable state.

## Parsing and Profiles

- V1 has exactly two parser engines: `native` for CLI/text and `jmespath` for JSON/API. **TTP is excluded**: no dependency, adapter, executable template, compatibility layer, or fallback.
- Keep Profile resources versioned, declarative, data-only, and self-contained under their `profile.yaml` root. Separate Actions, Features, parser resources, and Observation Schemas. No executable imports, callbacks, `eval`, or `exec` in resources.
- Validate Profiles and resources offline before network I/O. Use JSON Schema Draft 2020-12 for observations; root data is an object or array. Do not impose a universal cross-vendor schema or silently normalize output shapes.
- Develop NipStack Native incrementally against **representative, rights-cleared, sanitized** fixtures; its DSL is not fixed in advance. See the parser-specific instructions.

## Safety and reliability

- Treat network output and third-party Profile resources as untrusted. Keep TLS validation, SSH host-key verification, resource limits, timeouts, and path confinement secure by default; fail explicitly.
- Never commit, log, include in public Issues, or persist credentials, secrets, unredacted device configurations, or sensitive raw output.
- Never contact a real network device without **separate, explicit, scoped authorization**. Ordinary PR tests must be offline; real SSH and HTTP lab proofs are separate from CI.
- Do not import or publish private historical code or fixtures without provenance, rights, sanitization, and explicit approval.

## Documentation and decisions

- `docs/developer/NN-*.md`: **durable contributor guidance** for modules actually implemented, numbered consistently with workstreams 20–140. Commit it when useful, keeping it synchronized with code.
- `docs/architecture/NN-*.md`: consolidated **how/why** overview of behavior actually delivered, normally at the end of a major workstream, with verified examples, tradeoffs, limitations, and links to code/tests.
- `docs/adr/`: only significant architectural decisions, with context, options, consequences, and approval **before** affected code. No ADR for routine internal naming.
- Before coding, the Issue or a small stable public specification must contain the approved behavior and acceptance criteria. Do **not** wait for the final architecture overview to clarify required contracts.
- Do not create `.github/copilot-instructions.md`, `.github/prompts/`, `CLAUDE.md`, specialized agents, or skill files by default. A tool-specific adapter requires a demonstrated need and separate approval; `AGENTS.md` remains the shared source.

## Development, verification, and release boundaries

- Distribution and console command: `nipstack-core`; import package: `nipstack_core` under `src/nipstack_core/`. Target Python: **3.11–3.15**, subject to actual compatibility verification; initial/reference development interpreter: Python **3.12**. Do not claim support not yet tested.
- Use `pyproject.toml`, Hatchling, `uv`/`uv.lock`, Ruff, mypy (strict), pytest, and `py.typed`; do not weaken quality gates to make a PR green.
- Test with isolated synthetic or approved sanitized fixtures; FakeConnector/FakeSession are **test-only** and must not enter wheel/sdist. Run relevant lint, format, types, tests, and packaging checks; report `PASS`, `FAIL`, `NOT_RUN`, and `NOT_VERIFIED` truthfully.
- Apache-2.0 is the approved Core license (no mandatory CLA/DCO in V1); ensure the actual license file and applicable rights before publishing artifacts.
- Release requires **two distinct human approvals**: 140F release-candidate `GO/NO-GO` against exact version/SHA/artifact hashes and gate evidence, then 140G explicit authorization for tag, PyPI, and GitHub Releases. Neither a development approval nor a merged PR is release authorization.

## Scope-specific instructions

Nested `AGENTS.md` files refine these rules for their directories. Do not duplicate this document in every subdirectory.
