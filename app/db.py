import os

import psycopg

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://deltacode:deltacode@localhost:5432/deltacode"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id SERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    pr_number INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE runs ADD COLUMN IF NOT EXISTS clone_url TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS base_ref TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS base_sha TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS head_ref TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS head_sha TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS installation_id BIGINT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS error TEXT;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    github_user_id BIGINT NOT NULL,
    github_login TEXT NOT NULL,
    github_name TEXT,
    avatar_url TEXT,
    accessible_repos JSONB NOT NULL DEFAULT '[]',
    repositories JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS github_name TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS repositories JSONB NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS providers (
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, id)
);

CREATE TABLE IF NOT EXISTS repositories (
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    full_name TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'unknown',
    default_branch TEXT NOT NULL DEFAULT 'main',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, id),
    UNIQUE (workspace_id, full_name)
);

CREATE TABLE IF NOT EXISTS change_events (
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    provider_id TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    status TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, id),
    UNIQUE (workspace_id, provider_id, dedupe_key)
);

CREATE TABLE IF NOT EXISTS impact_assessments (
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    change_event_id TEXT NOT NULL,
    repository_id TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    capability_report JSONB NOT NULL DEFAULT '{}',
    data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, id),
    UNIQUE (workspace_id, change_event_id, repository_id, snapshot_digest)
);

CREATE TABLE IF NOT EXISTS migrations (
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    change_event_id TEXT NOT NULL,
    repository_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    current_attempt_id TEXT,
    snoozed_until TIMESTAMPTZ,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS migrations_one_active_per_change_repo
ON migrations (workspace_id, change_event_id, repository_id)
WHERE status NOT IN ('declined', 'completed');

CREATE TABLE IF NOT EXISTS migration_attempts (
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    migration_id TEXT NOT NULL,
    number INTEGER NOT NULL CHECK (number > 0),
    previous_attempt_id TEXT,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, id),
    UNIQUE (workspace_id, migration_id, number),
    UNIQUE (workspace_id, migration_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS developer_decisions (
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    migration_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    target_version INTEGER NOT NULL,
    reason TEXT,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, id)
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, operation, idempotency_key)
);

ALTER TABLE idempotency_records
ADD COLUMN IF NOT EXISTS request_hash TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS change_events_workspace_feed
ON change_events (workspace_id, created_at DESC, id);
CREATE INDEX IF NOT EXISTS migrations_workspace_feed
ON migrations (workspace_id, created_at DESC, id);
CREATE INDEX IF NOT EXISTS audit_events_workspace_feed
ON audit_events (workspace_id, created_at DESC, id);
"""


def get_connection() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


def init_schema() -> None:
    with get_connection() as conn:
        conn.execute(SCHEMA)
