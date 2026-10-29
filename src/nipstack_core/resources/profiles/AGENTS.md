# NipStack Core — Declarative Profile Guidance

This file supplements the repository-root and Python package `AGENTS.md` instructions.

## Structure and meaning

- Each Profile is self-contained, versioned, and described by one `profile.yaml` manifest plus resources under its own root.
- A Profile describes a logical platform/access variant, its main Connector (`ssh` or `http` in V1), explicit Actions, Features, parser resources, and Observation Schemas.
- Keep network acquisition **Actions** separate from structured observation **Features**. Features reference Action IDs; they do not embed commands or independently execute acquisition. One Action produces one RawArtifact in V1 and may feed several Features.
- Feature IDs have the canonical three-segment `<mode>.<group>.<feature>` structure. Do not invent lexical restrictions beyond the approved public contract, or hardcode `check` and `config` as the only valid modes.
- Do not add a generic Action DAG or Feature-to-Feature workflow. No implicit Feature selection and no automatic retries/fallbacks.

## Parsers, schemas, and identity

- Use `engine: native` for CLI/text and `engine: jmespath` for JSON/API. No TTP engine or `.ttp` resources.
- Use JSON Schema Draft 2020-12 for Feature observations; root data is an object or array. A common logical Feature ID does **not** require identical schema structure across Profiles. Do not impose an artificial vendor-neutral output schema.
- Maintain the exact Profile + Feature + SchemaIdentity contract. The approved SchemaIdentity canonicalization is **RFC 8785 / JCS** (`schema-c14n-v1`, SHA-256 lowercase `sha256:<64 hex>`); implement and verify it only in the responsible approved increment, never invent or approximate a digest.

## Security, validation, and versioning

- Profiles and templates are declarative data, never executable Python, imports, scripts, callbacks, or macros.
- Constrain all referenced resource paths to the Profile root; reject traversal, symlinks, invalid references, and unknown manifest fields as required by the accepted contract.
- Validate manifests, resources, input/parser compatibility, Observation Schemas, and Connector capabilities **offline before network acquisition**. Built-in Profiles must meet the same validation gate as external Profiles.
- Never embed credentials, private device addresses, unredacted configurations, or sensitive captured output in Profiles, fixtures, docs, or test logs. Verify fixture publication rights and sanitize consistently.
- Keep bundled Profile coverage deliberately minimal in V1: one approved official SSH Feature and one approved official HTTP Feature; additional parsing scenarios do not imply official support.
- Update Profile SemVer, tests, resources, and durable documentation when behavior or schema contracts change. Follow the shared Registry and explicit version/conflict policies; do not implement implicit override or latest-version fallback.
