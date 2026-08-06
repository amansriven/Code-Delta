# Phase 2: official-source ingestion

- **Status:** Implemented trusted-development foundation
- **Contract version:** `1.0`
- **Depends on:** [Phase 1 control plane](phase-1-control-plane.md) and
  [ADR 0001](decisions/0001-artifact-storage.md)

## Delivered boundary

Phase 2 turns configured official sources into immutable artifacts and ready,
provider-independent change events. It does not inspect repositories or decide
impact; each newly inserted ready event creates idempotent repository fan-out
jobs for Phase 3.

The implementation provides:

- versioned provider source, artifact descriptor, captured artifact, health,
  and ingestion-result contracts;
- authenticated, audited, idempotent provider and source registration;
- durable, deduplicated source-sync requests executed by the existing
  PostgreSQL-backed worker;
- a bounded HTTPS collector with official-domain checks, manual redirect
  validation, public-address enforcement, cache validators, media-type limits,
  response-size limits, decompression-ratio limits, timeouts, and redacted error
  codes;
- immutable SHA-256 filesystem artifact storage with read-time integrity
  verification and metadata retention timestamps;
- deterministic JSON OpenAPI diffs for endpoint additions/removals and newly
  required inline JSON request fields;
- a structurally different official structured-release adapter with explicit
  provider-stated provenance;
- atomic artifact metadata, normalized event, evidence-link, source health,
  provider health, and repository fan-out persistence; and
- tests for private/metadata addressing, host suffix attacks, redirect escape,
  redirect bounds, invalid media and sizes, decompression bombs, storage
  tampering, normalization, provenance, deduplication, health, and sync
  idempotency.

## Ingestion flow

```text
configured official source
  -> validate HTTPS host and every resolved address
  -> fetch with explicit redirect, byte, media, and time limits
  -> hash and capture immutable bytes
  -> compare with the prior artifact through a format adapter
  -> validate NormalizedChange 1.0
  -> atomically deduplicate and persist provenance
  -> queue each new ready event for connected repositories
  -> update source and provider health
```

Adapters receive captured bytes from `ArtifactStore`; they have no network
client and cannot follow links found inside an artifact.

## HTTP resources

```text
POST /providers
GET  /providers
POST /providers/{provider_id}/sources
GET  /providers/{provider_id}/sources
POST /providers/{provider_id}/sources/{source_id}/sync
GET  /changes
GET  /changes/{change_id}
```

All mutations require the authenticated session, trusted frontend `Origin`, and
an `Idempotency-Key`. Repeating a sync key returns its durable queued, running,
completed, or failed state without scheduling another job.

## Health semantics

- `never_synced`: enabled source has no successful capture.
- `healthy`: the latest attempt succeeded or was not modified.
- `degraded`: one or two consecutive attempts failed.
- `failing`: at least three consecutive attempts failed.
- `disabled`: collection is administratively disabled.

Only safe error codes enter source health. Response bodies, credentials, and
raw exception details are not stored there.

## Storage and deployment gate

Local development can set:

```bash
export ARTIFACT_STORAGE_ROOT="$PWD/.delta-code-artifacts"
```

Live ingestion must remain disabled unless this path is a shared, encrypted,
persistent volume and outbound traffic is also restricted by the deployment's
egress controls. Application DNS checks are defense in depth; the network layer
must independently block private, loopback, link-local, and metadata ranges to
eliminate DNS-rebinding races.

## Phase 3 handoff

The implemented [Phase 3 repository intelligence](phase-3-repository-intelligence.md)
consumes `change_fanout_jobs`, materializes immutable repository
snapshots, inventories dependencies and languages, locates call sites, and
creates supported impact assessments. It must preserve the normalized event's
artifact ids and claim provenance and must not treat a queued fan-out job as
evidence that a repository is affected.
