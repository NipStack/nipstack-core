# NipStack Core — Python Package Guidance

This file supplements the repository-root `AGENTS.md` for files in `src/nipstack_core/`.

## Module boundaries

- `contracts/`: typed public request, selection, result, error, artifact, and event contracts; depend on the standard library only, not on implementation modules or third-party connector/parser types.
- `profiles/`: declarative manifest loading, model validation, and the validated ProfileRegistry.
- `catalog/`: read-only view of the **same** validated ProfileRegistry used by collection.
- `planning/`: pure Feature resolution and deterministic, immutable execution plans; no network I/O.
- `execution/`: orchestrate collection and Action execution without embedding transport/parser-library logic.
- `connectors/`: transport, authentication boundary, and Session lifecycle; no Feature-specific policy.
- `parsers/`: local transformations only; no network or application persistence.
- `validation/`: Observation Schema validation separately from parsing.
- `exporters/`, `cli/`: thin adapters of the same Core contracts; no parallel business logic.

## Coding and contract rules

- Use clear Python types, focused modules, dataclasses, enums, Protocols, and small dependency-injection seams where appropriate. Avoid circular imports, generic global `utils.py`, oversized managers, and unnecessary runtime dependencies.
- Stable public APIs must not expose third-party implementation objects or exceptions. Export only approved public types; do not add speculative root exports or placeholder implementations.
- Keep runtime mutable state per Collection, with one Session per Collection; share immutable validated registries/prepared resources. V1 Action execution is sequential and each required Action ID is acquired at most once.
- Invalid Python-level construction may raise a public usage exception **where its contract defines one**; a syntactically valid Feature unknown to the selected Profile is a **resolution-time** problem, not an invented constructor restriction.
- Translate operational failures at module boundaries into structured sanitized NipStack Core errors; never turn a failure into an empty success result. Preserve provenance and cancellation/partial-result semantics.
- Use standard-library logging without changing global logging configuration; never log raw sensitive observations or credentials.
- Test pure real components directly and substitute fakes only at external boundaries. No real-network calls in routine unit/integration tests.
- Implement only contracts explicitly approved in the current Issue or stable public specification, with matching tests. Follow root documentation and review rules.
