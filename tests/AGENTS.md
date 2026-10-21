# NipStack Core — Testing Guidance

This file supplements repository-root `AGENTS.md` for tests and fixtures.

- Use pytest and risk-based coverage, not arbitrary coverage percentage targets.
- Keep standard PR tests offline, isolated, reproducible and deterministic. Place live-device tests in a separate lab workflow that is not required for normal CI.
- Unit-test pure components directly; use FakeConnector/FakeSession at the external I/O boundary to exercise the actual Collection pipeline.
- Verify Profile loading, Feature resolution, deterministic planning, Action deduplication, Session cleanup, RawArtifact provenance, parser results, schema validation, results, errors and partial success.
- Provide sanitized golden fixtures for official Features: raw input(s), parser resource, expected FeatureData and Observation Schema.
- Cover malformed templates, parser edge cases, unsupported capabilities, absent versus empty fields, schema incompatibilities and regression cases.
- Test security properties including credentials sanitization, no raw output in errors/logs, path traversal rejection, unsafe YAML, resource limits and timeouts.
- Keep serialization and SchemaIdentity behavior stable and explicitly tested.
- Benchmarks are separate from standard CI and must exclude device/network latency using fakes. Report actual CPU/memory measurements rather than guessed performance.
- Never claim checks passed unless executed; document checks skipped and why.
