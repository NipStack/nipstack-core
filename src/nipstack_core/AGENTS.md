# NipStack Core — Python Package Guidance

This file supplements the repository-root `AGENTS.md` for files in `src/nipstack_core/`.

## Responsibilities

- `contracts/`: public request, result, error, artifact and event contracts; no dependency on implementations.
- `profiles/`: manifest loading, declarative model validation, and ProfileRegistry.
- `catalog/`: read-only view of the validated ProfileRegistry.
- `planning/`: pure Feature resolution and immutable execution plans, no network I/O.
- `execution/`: orchestrate collection and Action execution; no transport- or parser-library implementation details.
- `connectors/`: network transport, authentication boundary and Session lifecycle; no Feature knowledge.
- `parsers/`: pure local data transformations; no network or database access.
- `validation/`: Observation Schema validation, separate from parsing.
- `exporters/`, `cli/`: thin adapters of the same core contracts; no parallel business logic.

## Coding rules

- Use clear Python types, dataclasses, enums, Protocols, focused modules, and lightweight dependency injection where useful.
- Keep dependency directions explicit; avoid circular imports, generic global `utils.py` and unbounded Manager abstractions.
- Do not expose third-party implementation objects or exceptions through stable public APIs.
- Keep per-Collection mutable state isolated; shared registries and prepared resources should be immutable.
- Keep Collection execution synchronous and Action execution sequential inside one Session in V1.
- Translate boundary failures into structured, sanitized NipStack Core errors, without turning failures into empty success results.
- Use standard-library logging without global logging configuration; do not log raw data or credentials.
- Implement tests with the smallest practical real components and fakes only at external boundaries.
