# ADR 0001: content-addressed source artifact storage

- **Status:** Accepted for the trusted-development MVP
- **Date:** 2026-08-05
- **Applies to:** Phase 2 ingestion

## Decision

Source bodies are stored through the `ArtifactStore` contract. The initial
backend is an immutable content-addressed filesystem rooted at
`ARTIFACT_STORAGE_ROOT`. Hosted deployments must mount that path on an encrypted
persistent volume; the `/tmp/delta-code-artifacts` fallback is development-only.

Objects use `sha256/<prefix>/<digest>` keys derived solely from verified bytes.
Creation is exclusive, existing objects are never overwritten, and reads
recompute the digest. PostgreSQL stores only workspace-scoped metadata and the
opaque object reference.

Each source has a configurable retention period of 1–3,650 days, defaulting to
90 days. Every artifact receives an `expires_at` timestamp and the retention
index supports a bounded lifecycle worker. Audit identifiers and digests can be
retained after content expiry according to workspace policy.

## Consequences

- Collectors and adapters do not depend on a storage vendor.
- Identical bytes converge on one immutable object key while tenant metadata
  remains separately authorized.
- Railway or another hosted runtime must attach an encrypted persistent volume
  before live ingestion is enabled.
- A production object-store backend can replace the filesystem implementation
  without changing normalized changes or ingestion jobs.
- Multi-instance ingestion requires shared storage; an instance-local disk is
  not a supported hosted configuration.
