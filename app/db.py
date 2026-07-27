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
"""


def get_connection() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


def init_schema() -> None:
    with get_connection() as conn:
        conn.execute(SCHEMA)
