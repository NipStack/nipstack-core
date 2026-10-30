# Contributing to NipStack Core

Thank you for helping develop **NipStack Core**, an open-source Python library for collecting, parsing, and validating network observations.

NipStack Core V1 is under active development. **Do not assume that planned interfaces or Features are already implemented.** Check the current code, tests, Issues, and documentation.

## Before you start

Read these public resources in this order:

1. [Repository instructions](AGENTS.md), followed by any more specific `AGENTS.md` files relevant to your change.
2. [Coding standards](docs/developer/coding-standards.md).
3. The GitHub Issue and any accepted public contract or ADR it references.
4. Existing code, tests, and the current CI workflow.

The rules apply equally to humans, GitHub Copilot, Codex, Claude Code, and other contributors. You do **not** need access to a private planning repository or an earlier chat.

## Choose a focused task

- Prefer an existing GitHub Issue describing one bounded, verifiable increment (for example, `20A`).
- An Issue must give the objective, scope, exclusions, constraints, and measurable acceptance criteria. Request clarification when a required contract is missing.
- For a new API, architectural decision, or substantial change, **propose a plan first**: affected files, public contract, alternatives, tests, risk, and validation commands.
- **Do not start modifying files until the plan and any open public-contract decisions have been approved.** Small routine corrections should still follow the repository's review and authorization rules.
- Never interpret an Issue as permission to access devices, expose private material, publish packages, or change the approved architecture.

## Development environment

The baseline is Python **3.11 or later**, with Python **3.12** as the initial/reference development interpreter. The broader V1 target is Python 3.11–3.15, **subject to actual verification**. Use `uv` and the checked-in lockfile.

```bash
git clone https://github.com/NipStack/nipstack-core.git
cd nipstack-core
uv python install 3.12
uv sync --locked --python 3.12
```

Do not add unnecessary runtime or development dependencies. When a new dependency is needed, explain its purpose, security/packaging impact, and obtain approval before changing the environment or lockfile.

## Branches, commits, and Pull Requests

Create a short-lived branch from current `main`:

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/20a-feature-selection
```

Use a descriptive branch name; this example is only illustrative. Keep each PR scoped to a single approved Issue or tightly related change.

Use a concise Conventional Commits-style title, such as `feat: implement feature selection contract` or `docs: document coding standards`.

Before opening a PR, describe:

- The linked Issue (`Closes #123` **only when the PR really completes that Issue**).
- What changed and why, including any public-contract or compatibility impact.
- Tests and checks actually run, with **PASS / FAIL / NOT_RUN / NOT_VERIFIED** and explanations.
- Relevant security concerns, known limitations, unresolved decisions, and documentation changes.

Respect required CI, review, and protected `main`. The preferred merge method is **Squash and merge**, after approval. Do not push, merge, tag, or publish without authorization.

## Quality checks

Run checks appropriate to the modification:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q
uv build
```

The GitHub Actions workflow defines required CI checks, including the configured Python matrix and package installation smoke tests. Do not claim a check passed unless it actually ran; report justified omissions.

Use offline deterministic tests and synthetic or explicitly approved sanitized fixtures. Network hardware tests are separate and require explicit, scoped authorization. Do not ship FakeConnector/FakeSession in distributions.

## Documentation policy

- Follow the [coding standards](docs/developer/coding-standards.md) for clarity, comments, docstrings, typing, tests, and maintainability.
- Put **durable** contribution guidance in `docs/developer/`, with numbered workstream guides as implemented functionality grows.
- Consolidate *implemented* system explanations in `docs/architecture/` after major workstreams.
- Reserve `docs/adr/` for significant approved architectural decisions.
- Keep temporary task prompts, agent plans, and acceptance discussions in the GitHub Issue or PR, not in permanent documentation files.
- Update public docs alongside the code they describe. Do not publish unapproved private design notes or fictitious examples.

## Security and licensing

- Never submit credentials, tokens, private keys, sensitive device outputs, unredacted real configurations, or private repository content without authorization and sanitization.
- Do not add network operations to routine tests. Preserve secure TLS/SSH defaults and resource limits.
- This project uses the [Apache License, Version 2.0](LICENSE). Only contribute material you have the right to submit under the project's license, and preserve applicable third-party notices. V1 does not require a separate CLA or DCO sign-off.
- For a potential security vulnerability, **do not publish exploit details or secrets in a public Issue**. Contact the maintainers privately using an available GitHub private-reporting channel; if none is configured, request a private reporting route without disclosing details.

Thank you for helping keep NipStack Core straightforward, safe, testable, and maintainable.
