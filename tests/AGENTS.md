# NipStack Core — Testing Guidance

This file supplements repository-root `AGENTS.md` for tests and fixtures.

## Test scope and isolation

- Use pytest with risk-based coverage, not arbitrary percentage targets. Keep ordinary PR tests deterministic, offline, isolated, and reproducible.
- Unit-test real pure components directly. Use FakeConnector/FakeSession **only at the external transport boundary** to exercise the actual Collection pipeline; do not mock away the resolver, planner, parser, or schema validator when a real pipeline test is intended.
- When introduced, fakes belong in **`tests/fakes/`**, never in the importable production package or bundled wheel/sdist. Test resources must not hide missing production capabilities.
- Verify Profile loading and rejection, Feature resolution, deterministic planning, Action ID deduplication, Session lifecycle/cleanup, provenance, parsing, schema validation, statuses, partial results, and cancellation at the appropriate workstream stage. Do not require unfinished future modules to exist for an early increment.
- Include invalid-construction tests separately from resolution-time invalid/unknown selections where the API contract requires that distinction.

## Golden fixtures and security

- Use synthetic or explicitly authorized, rights-cleared, coherently sanitized fixtures. Prefer concise excerpts covering distinct real variations; never publish raw historic configurations, secrets, credentials, or unauthorized device output.
- Golden scenarios for official Features include acquisition input(s), parser resource, expected FeatureData, and Observation Schema. Preserve absent vs valid-empty vs failed semantics.
- Cover malformed templates, unsafe YAML/path traversal/symlinks, invalid schemas, unsupported capabilities, resource budgets, security defaults, credential/redaction handling, parser edge cases, and regressions as the responsible components become available.
- Where relevant, test **RFC 8785 / JCS** SchemaIdentity with independent fixed golden vectors; test JMESPath inputs using the approved Action-ID-keyed root mapping (including a single input).

## Evidence levels, packaging, and reporting

- **L1:** pure offline validation/parsing and golden tests.
- **L2:** genuine `collect()` through a test FakeConnector/FakeSession, offline; proves the pipeline, **not a network connection**.
- **L3:** actual transport adapter exercised against a mock or controlled local test service; no real device without authorization.
- **L4:** real SSH/HTTP lab execution **only after separate, explicit, scoped authorization**. Maintain independent SSH and HTTP evidence for G3; do not add live-device tests to ordinary PR CI.
- Test source checkout and, when required by the incremental acceptance gate, **installed wheel and sdist** with bundled resources/entry point. Do not infer distribution correctness from import smoke tests. Check fakes are absent from both artifacts.
- Benchmarks are outside standard CI, separate CPU/memory work from device latency, and record environment, commit, inputs, and observed measurements.
- Report the actual outcome of Ruff, mypy, pytest, packaging, and other applicable checks as `PASS`, `FAIL`, `NOT_RUN`, or `NOT_VERIFIED`. A green general CI run does not by itself validate G0–G4 or authorize a release.
