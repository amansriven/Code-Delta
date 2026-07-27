import os

import psycopg

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://codedelta:codedelta@localhost:5432/codedelta"
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
    avatar_url TEXT,
    accessible_repos JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
"""


def get_connection() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


def init_schema() -> None:
    with get_connection() as conn:
        conn.execute(SCHEMA)
