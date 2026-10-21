# NipStack Core — Declarative Profile Guidance

This file supplements the repository-root and Python package `AGENTS.md` instructions.

## Structure and meaning

- Each Profile is self-contained, versioned and described by one `profile.yaml` manifest and its own local resources.
- The Profile identifies a logical platform/access variant, Connector, explicit Actions, Features, parser resources and Observation Schemas.
- Keep the distinction between a network Action (acquisition) and a Feature (structured observation). A Feature references one or more Action IDs and does not embed network commands.
- Keep Feature IDs in `<mode>.<group>.<feature>` form. Each Feature declares scope, inputs, parser and schema explicitly.
- A single Action produces one RawArtifact in V1 and can feed several Features. Do not introduce a generic Action DAG or Feature-to-Feature workflow.
- An individual Profile uses one main Connector (`ssh` or `http`) in V1.

## Parsing and schemas

- `engine: native` for CLI/text templates (`parser.yaml`); `engine: jmespath` for JSON/API (`parser.jmespath`). No TTP engine or `.ttp` resources.
- Use JSON Schema Draft 2020-12 for `schema.json`. Schema constraints describe observations, not UI forms, compliance or application-specific business policy.
- The exact contract is Profile + Feature + SchemaIdentity; Feature IDs may represent common concepts without requiring identical schemas across platforms.
- Do not normalize data into an artificial universal vendor schema.

## Safety, validation and versioning

- Templates and actions are declarative; no Python, arbitrary imports, embedded callbacks or executable macros.
- Only use relative resource paths confined to the Profile root; reject traversal, symlinks, invalid references and unknown manifest fields.
- Validate Profile manifests, resource existence, input/parser compatibility and schemas before network acquisition.
- Never store credentials or unredacted sensitive configurations in resources or fixtures.
- Update Profile SemVer, fixtures and documentation as required by behavioral or schema changes.
