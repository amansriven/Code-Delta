# Delta Code architecture

This directory defines the product and technical contracts for Delta Code's
evolution into an API change-management and migration platform.

Phase 0 is intentionally documentation-only. These documents describe the
boundaries that the database, workers, GitHub integration, LLM adapters,
sandbox, and dashboard must follow before those systems are changed.

## Phase 0 documents

- [Product RFC](phase-0-rfc.md) — product boundary, experience, architecture,
  scope, success measures, and delivery gates.
- [Domain model](domain-model.md) — durable entities, ownership rules, and
  lifecycle state machines.
- [System contracts](contracts.md) — provider adapters, repository analyzers,
  migration intelligence, sandbox execution, verification, and publishing.
- [Security and permissions](security-and-permissions.md) — trust boundaries,
  GitHub permissions, token handling, sandbox policy, and LLM data controls.
- [Normalized change schema](schemas/normalized-change.schema.json) — the
  provider-independent output of change ingestion.
- [Migration evidence schema](schemas/migration-evidence.schema.json) — the
  repository-specific evidence used by the dashboard and draft PRs.
- [Example normalized change](examples/normalized-change.example.json) and
  [example migration evidence](examples/migration-evidence.example.json) — a
  fixture vertical slice used to validate both contracts.

## Decision status

The product direction and architectural boundaries are accepted. Provider
selection, the production sandbox vendor, and initial language coverage remain
explicit implementation decisions. No provider-specific decision may weaken
the common contracts defined here.

## Phase 0 exit criteria

Phase 0 is complete when:

1. The product boundary and non-goals are agreed upon.
2. Change, impact, migration, attempt, evidence, and decision lifecycles are
   unambiguous.
3. Provider and repository integrations depend on common contracts.
4. Deterministic evidence is distinguishable from model interpretation.
5. GitHub write permissions and sandbox risks are documented before enablement.
6. Both JSON Schemas parse successfully and cover the first vertical slice.
7. Remaining implementation choices are recorded as decisions rather than
   hidden assumptions.
