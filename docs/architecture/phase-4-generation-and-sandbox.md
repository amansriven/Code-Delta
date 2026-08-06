# Phase 4 — migration generation and sandbox verification

Phase 4 turns an affected Phase 3 assessment into an immutable, reviewable
migration attempt. The trusted application process assembles bounded context,
validates structured output, stores a content-addressed patch artifact, and
delegates every repository-controlled command to a separate Cloudflare Sandbox
Worker. It never edits the checked-out repository in place and never executes
repository commands itself.

## Implemented flow

1. `POST /migrations/{migration_id}/generate` requires an authenticated
   workspace, a trusted browser origin, an idempotency key, and the migration's
   expected version.
2. The transaction creates or reuses a revision attempt, moves the migration
   and attempt to `planning`, writes an audit event, and records the response
   under the idempotency key.
3. A Procrastinate job claims the attempt, checks out the exact persisted commit
   SHA using an opaque GitHub installation handle, and verifies the checkout's
   deterministic content digest against the Phase 3 snapshot.
4. Context assembly includes only evidence-linked call-site and dependency
   files, at most 20 files and 1 MB. Credential-like text is redacted, large
   change values are replaced by a digest, and repository/provider text is
   explicitly marked untrusted. A developer's bounded revision instructions
   are carried into the new immutable attempt context.
5. A dedicated HTTPS migration-intelligence gateway returns a schema-validated
   plan and structured full-file edits. The gateway receives no GitHub,
   database, sandbox, or model-provider credentials from Delta Code.
6. The trusted worker rejects path traversal, CI/workflow edits, credential
   files, key material, stale file digests, unplanned paths, secret-like output,
   oversized patches, and non-allowlisted verification executables.
7. The canonical structured patch is stored in the existing immutable artifact
   store. A bounded repository bundle and the edits are sent to the authenticated
   sandbox executor.
8. The Sandbox Worker verifies every file digest, writes into `/workspace`,
   shell-quotes individual argv values, runs bounded checks with outbound
   traffic disabled, redacts and truncates logs, and destroys the sandbox in a
   `finally` block. Every execution uses a new sandbox identifier.
9. A schema-validated review and recommendation become `MigrationEvidence`.
   Approval is downgraded unless all deterministic checks pass and sandbox
   teardown is confirmed. The attempt, patch metadata, final migration state,
   and audit event are committed together.

## Trust boundaries

The application and generation worker are trusted orchestration components.
The repository, provider text, model gateway responses, and sandbox logs are
untrusted inputs. The Cloudflare container is the only component allowed to
execute repository code.

The executor follows Cloudflare's current RPC transport and per-request
session guidance. `enableInternet = false` denies outbound sandbox traffic, and
the whole sandbox is destroyed after a command timeout because a command-level
timeout does not itself terminate the underlying process. See Cloudflare's
[security model](https://developers.cloudflare.com/sandbox/concepts/security/),
[outbound traffic controls](https://developers.cloudflare.com/sandbox/guides/outbound-traffic/),
and [current SDK migration guidance](https://developers.cloudflare.com/sandbox/guides/2026-deprecation/).

The worker rejects responses whose attempt identity, executor identity, or
ordered check set differs from the request. It also rejects an internally
inconsistent success response. Only safe error codes—not exception messages or
credentials—are persisted on failed attempts.

## Configuration

The generation worker requires all of the following:

```text
MIGRATION_INTELLIGENCE_URL=https://...
MIGRATION_INTELLIGENCE_TOKEN=...
SANDBOX_EXECUTOR_URL=https://...
SANDBOX_EXECUTOR_TOKEN=...
SANDBOX_EXECUTION_ENABLED=true
ARTIFACT_STORAGE_ROOT=/encrypted/persistent/path
```

`SANDBOX_EXECUTION_ENABLED` is fail-closed: only the exact case-insensitive
value `true` enables execution. Missing gateway URLs, missing tokens, non-HTTPS
URLs, embedded URL credentials, or a disabled execution flag fail the attempt
into a visible `blocked` state.

The same bearer token must be installed as the Worker's
`SANDBOX_EXECUTOR_TOKEN` secret; it must not appear in `wrangler.jsonc` or a
container image. `ARTIFACT_STORAGE_ROOT` must be an encrypted persistent volume
in hosted environments.

## Worker development and deployment gate

Install and validate the Worker independently:

```bash
make sandbox-setup
make test-sandbox
cd sandbox-worker
npx wrangler deploy --dry-run
```

Do not set `SANDBOX_EXECUTION_ENABLED=true` in a hosted environment until the
Worker has been deployed with its secret and isolation tests have confirmed:

- outbound DNS and HTTP are denied;
- control-plane, metadata, token-broker, and private-network endpoints cannot
  be reached;
- filesystem writes do not survive sandbox destruction;
- command timeouts are followed by sandbox destruction;
- concurrent attempts cannot observe each other's files or processes;
- logs and API responses do not expose seeded credentials.

The checked-in Worker uses one `lite` container instance to keep initial
development cost bounded. Production capacity, queue backpressure, regional
placement, and retention monitoring must be set deliberately before broad
enablement.

## Current boundary

Phase 4 produces plans, structured patch artifacts, deterministic check
evidence, reviews, recommendations, and durable attempts. It never applies
patches to Git itself; Phase 5 consumes only its immutable artifact and evidence
through the separate publisher boundary. The HTTP intelligence gateway is a
deliberate provider-neutral seam, not a model-provider-specific implementation
in this repository.
