# NipStack Core — Coding Standards

> Scope: permanent Python development and review standards for the public `nipstack-core` repository.
>
> These standards apply to human contributors and AI coding agents alike. Follow the repository and scoped `AGENTS.md` files, accepted public contracts, and approved ADRs as well. This guide describes **how to write and review code**; it does not authorize features, redefine architecture, or replace a task Issue.

## 1. Guiding principles

- **Maintainability over cleverness.** Write for the next contributor who must understand or change the code.
- **Explicit behavior over hidden magic.** Inputs, outputs, errors, side effects, dependencies, and execution order should be understandable.
- **Simple design over premature abstraction.** Add abstraction only when a concrete, stable common rule makes the code easier to maintain.
- **Correctness and security over shortcuts.** No workaround that silently drops data, hides errors, or weakens safety.
- **Consistency over personal preference.** Follow the repository's established style and tooling.
- Do **not** impose arbitrary function/class line-count limits. Judge responsibilities, nesting, readability, and testability instead.

These principles apply to each change in proportion to its actual risk. Do not introduce architecture or extensive documentation for a trivial modification.

## 2. Readable code and responsibilities

- Prefer short, clearly named steps over compressed expressions with several conditions.
- Give each function, class, and module a responsibility that can be explained plainly.
- Extract a function when it improves understanding, reuse, or testing—not just to reduce line count.
- Keep local code local when reuse is speculative. Small duplication is acceptable when it avoids a premature generic framework.
- Avoid catch-all modules such as `utils.py`, `helpers.py`, `common.py`, or universal `Manager` classes.
- Prefer direct, typed functions. Use classes, dataclasses, Protocols, and dependency injection only where their responsibilities justify them.
- Separate pure data transformation from I/O and runtime orchestration.
- Do not implement speculative future features, generic adapters, backwards-compatibility layers, or placeholders without an approved need.

### Naming conventions

| Element | Convention | Example |
| --- | --- | --- |
| Files, modules, variables, functions | `snake_case` | `feature_selection`, `resolve_features` |
| Classes and exceptions | `PascalCase` | `CollectionRequest`, `NipStackCoreUsageError` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RESOURCE_BYTES` |
| Boolean predicates | `is_`, `has_`, `can_`, `requires_` | `is_valid`, `has_features` |
| Public symbols | Precise, consistent, domain-oriented | Avoid vague `data`, `obj`, `process`, `flag` |

Use **English** for code, comments, docstrings, logs, and public technical documentation.

## 3. Python types, contracts, and validation

- Prefer standard-library types, `dataclasses`, `Enum`, `Protocol`, and precise type annotations supported by the repository's Python compatibility baseline.
- Type public interfaces, module boundaries, nontrivial callbacks, and non-obvious return values.
- Avoid unnecessary `Any`, broad unions, unchecked casts, `# type: ignore`, and dynamically shaped dictionaries. Justify localized exceptions.
- Public contracts must not expose third-party transport, parsing, or validation implementation types.
- Design immutable values where required; a frozen dataclass containing mutable objects is **not** deeply immutable. Use copies or immutable representations as needed.
- Validate untrusted inputs and public boundary invariants explicitly. Do not repeat the same validation at every internal call site after a trusted contract is established.
- Preserve the distinction between missing, `None`, empty, successful, and failed data according to the approved contract; do not coerce them silently.
- Keep names and signatures in examples aligned with **implemented** APIs. A planned API must be labeled as a proposal.

## 4. Dependencies, side effects, and error handling

- Follow the module ownership and dependency directions in `src/nipstack_core/AGENTS.md`. In particular, contracts remain standard-library-only, planning is pure, Connectors own transport, and parsers have no network I/O.
- Make side effects visible in function names and control flow. Read-oriented functions must not unexpectedly connect to devices, mutate durable state, or publish events.
- Do not use global mutable Session, Target, credential, or Collection state.
- Handle exceptions deliberately: let a meaningful error propagate or translate it at the correct boundary into the approved sanitized error model.
- Never write `except Exception: pass`, treat operational failure as an empty success, or return a string beginning with `ERROR:` as observation data.
- A broad catch is acceptable only at a deliberate isolation boundary, when necessary for the documented failure contract and with tests.
- Keep external dependencies isolated behind their owning modules. Do not add runtime packages, caches, pools, retries, or concurrency without approval and demonstrated need.

## 5. Comments and docstrings

**Comments explain why, not what.** Write comments for invariants, security reasons, tricky edge cases, measured trade-offs, or non-obvious limitations.

Good:

```python
# Check resource confinement before reading: a Profile must not escape its root.
```

Avoid:

```python
# Set the value to None.
value = None
```

Before adding a long comment to explain difficult code, first consider clearer names, smaller responsibilities, or a simpler implementation.

- Use **Google-style docstrings** for nontrivial public interfaces, protocols, extension points, and complex algorithms.
- Describe important guarantees, preconditions, security constraints, side effects, and exceptions. Use `Args`, `Returns`, and `Raises` when they add information.
- Do **not** require a docstring for every obvious property, private helper, or simple forwarding function.
- Update or remove comments and docstrings when behavior changes. Never leave obsolete commented-out implementations; Git keeps history.
- TODO/FIXME notes must be actionable; include a reason and, when practical, a GitHub Issue reference.
- Do not place credentials, sensitive outputs, copied production configurations, or unsupported performance claims in comments or examples.

## 6. Security and observability

- Treat network responses and Profile resources as untrusted; enforce validated inputs, safe resource paths, finite limits, and explicit failures.
- Keep TLS verification and SSH host-key checking enabled by default. Never weaken safeguards to make a test pass.
- Do not publish secrets, sensitive real device output, or private fixtures in code, documentation, Issue bodies, error messages, tests, or logs.
- Use `logging.getLogger(__name__)` for library diagnostics; never set global logging configuration or use `print()` from library internals. The CLI may own its stdout/stderr.
- Log only necessary, non-sensitive context. Avoid duplicate reporting of the same error across layers.
- Keep real-device testing separate from normal CI and obtain explicit, scoped authorization before any network access.

## 7. Tests, reproducibility, and performance

- Add focused tests for observable contracts, negative cases, boundary conditions, and security invariants. A bug fix should include a regression test.
- Keep normal unit/integration tests **offline, deterministic, isolated, and reproducible**.
- Test real pure components directly. Substitute FakeConnector/FakeSession only at external boundaries; these test fakes are not shipped in wheel/sdist.
- For an official Feature, maintain approved, sanitized golden fixtures: input, parser definition, expected structured data, and Observation Schema.
- Verify invalid/empty/malformed input, partial failure, cleanup, error sanitization, and performance/resource limits where relevant.
- Use descriptive test names. Prefer risk-based coverage over a blanket percentage target.
- Use targeted property-based testing only when it materially covers invariants; do not add Hypothesis or any dependency without explicit approval.
- Measure CPU, peak memory, and parser behavior on representative offline cases **before** introducing optimizations. Network latency is not a parser benchmark.
- A passing CI workflow is not evidence that unexecuted lab, security, package, or release gates have passed.

### Repository checks

Follow the current `pyproject.toml` and `.github/workflows/ci.yml`. Typical local commands:

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q
uv build
```

The project currently uses Ruff, strict mypy, pytest, uv, and Hatchling. Do not stack Black/isort/Flake8 on top of Ruff or weaken lint/type/test configuration just to pass CI. Report checks as **PASS / FAIL / NOT_RUN / NOT_VERIFIED** with relevant reasons.

## 8. Documentation accompanies real changes

- Add/update docstrings and code comments where needed **in the same PR** as the behavior change.
- Keep durable contributor guidance under `docs/developer/`; use the workstream numbering `20–140` for workstream-specific guides.
- At the end of a major workstream, consolidate verified architecture and examples in `docs/architecture/`.
- Record only significant architectural decisions in `docs/adr/`, with approval before the affected implementation.
- Use self-contained public GitHub Issues and PR descriptions for **temporary increment specifications, review notes, and agent plans**. Do not commit a prompt file for each lot.
- Never make the public project depend on private documentation or a prior conversation to understand an implementation.
- Distinguish **implemented**, **proposed**, and **not yet verified** behavior. Do not claim that examples or guarantees exist before they do.

## 9. Pull Request review checklist

Before requesting review, verify that:

- [ ] The Issue scope and approved contract are respected; no unapproved extra functionality or dependency was introduced.
- [ ] Code is simple and readable, with clear names, limited responsibilities, and no unnecessary abstraction.
- [ ] Type boundaries, exceptions, module dependencies, and observable side effects are explicit.
- [ ] Comments explain important **reasons**; docstrings describe relevant guarantees without repeating obvious code.
- [ ] No secrets, sensitive raw outputs, or unapproved fixtures are exposed.
- [ ] No commented-out legacy code, dead helpers, unexplained ignores, or untracked TODOs remain.
- [ ] Offline tests cover important success, failure, security, and regression cases.
- [ ] Appropriate stable docs are updated and actual checks are reported accurately.
- [ ] The PR is linked to its Issue, reviewed, and subject to protected `main` checks.
- [ ] No tag, release, PyPI upload, or real-network test is attempted without separate authorization.

**Bottom line:** write NipStack Core as a small, explicit, secure and maintainable Python library—not as a collection of agent-generated abstractions.
