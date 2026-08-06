"""PostgreSQL persistence for the Phase 1 control plane."""

import base64
import binascii
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.control_plane.state import MIGRATION_TRANSITIONS, validate_transition
from app.db import get_connection


class NotFoundError(LookupError):
    pass


class IdempotencyConflictError(ValueError):
    pass


def workspace_id_for(session: dict) -> str:
    return f"github:{session['github_user_id']}"


def ensure_workspace(session: dict) -> str:
    workspace_id = workspace_id_for(session)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO workspaces (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (workspace_id, f"{session['github_login']}'s workspace"),
        )
        for repository in session.get("repositories", []):
            repository_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"github:{repository['full_name']}"))
            now = datetime.now(UTC)
            repository_data = {
                "id": repository_id,
                "full_name": repository["full_name"],
                "default_branch": repository.get("default_branch", "main"),
                "enabled": True,
                "languages": [],
                "providers": [],
                "updated_at": now.isoformat(),
            }
            conn.execute(
                """INSERT INTO repositories
                   (id, workspace_id, full_name, visibility, default_branch, data)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (workspace_id, full_name) DO UPDATE SET
                     visibility = EXCLUDED.visibility,
                     default_branch = EXCLUDED.default_branch,
                     data = repositories.data || jsonb_build_object(
                       'updated_at', now(), 'default_branch', EXCLUDED.default_branch
                     ),
                     updated_at = now()""",
                (
                    repository_id,
                    workspace_id,
                    repository["full_name"],
                    repository.get("visibility", "unknown"),
                    repository.get("default_branch", "main"),
                    json.dumps(repository_data),
                ),
            )
    return workspace_id


def _decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
        timestamp, entity_id = decoded.split("|", 1)
        return datetime.fromisoformat(timestamp), entity_id
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid cursor") from exc


def _encode_cursor(created_at: datetime, entity_id: str) -> str:
    value = f"{created_at.isoformat()}|{entity_id}".encode()
    return base64.urlsafe_b64encode(value).decode()


def list_records(
    workspace_id: str,
    table: str,
    columns: list[str],
    *,
    cursor: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None]:
    allowed_tables = {"change_events", "migrations", "providers", "repositories", "audit_events"}
    if table not in allowed_tables:
        raise ValueError("unsupported control-plane resource")
    position = _decode_cursor(cursor)
    selected = ", ".join(columns)
    where = "workspace_id = %s"
    params: list[Any] = [workspace_id]
    if position:
        where += " AND (created_at, id::text) < (%s, %s)"
        params.extend(position)
    params.append(limit + 1)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT {selected} FROM {table} WHERE {where} "  # noqa: S608
            "ORDER BY created_at DESC, id::text DESC LIMIT %s",
            params,
        ).fetchall()
    page_rows = rows[:limit]
    items = [dict(zip(columns, row, strict=True)) for row in page_rows]
    next_cursor = None
    if len(rows) > limit and page_rows:
        indexed = dict(zip(columns, page_rows[-1], strict=True))
        next_cursor = _encode_cursor(indexed["created_at"], str(indexed["id"]))
    return items, next_cursor


def get_record(workspace_id: str, table: str, entity_id: str) -> dict[str, Any]:
    allowed_tables = {"change_events", "migrations", "migration_attempts"}
    if table not in allowed_tables:
        raise ValueError("unsupported control-plane resource")
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT data FROM {table} WHERE workspace_id = %s AND id = %s",  # noqa: S608
            (workspace_id, entity_id),
        ).fetchone()
    if not row:
        raise NotFoundError(entity_id)
    return row[0]


def get_migration(workspace_id: str, migration_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT data FROM migrations WHERE workspace_id = %s AND id = %s",
            (workspace_id, migration_id),
        ).fetchone()
        if not row:
            raise NotFoundError(migration_id)
        attempts = conn.execute(
            """SELECT data FROM migration_attempts
               WHERE workspace_id = %s AND migration_id = %s ORDER BY number DESC""",
            (workspace_id, migration_id),
        ).fetchall()
    result = dict(row[0])
    result["attempts"] = [attempt[0] for attempt in attempts]
    return result


ACTION_STATES = {
    "approve": "approved",
    "revise": "needs_revision",
    "snooze": "snoozed",
    "decline": "declined",
}


def apply_developer_action(
    workspace_id: str,
    migration_id: str,
    action: str,
    *,
    actor: str,
    expected_version: int,
    idempotency_key: str,
    reason: str | None,
    instructions: str | None,
    snooze_until: datetime | None,
) -> dict[str, Any]:
    if action not in ACTION_STATES:
        raise ValueError("unsupported developer action")
    operation = f"migration:{migration_id}:{action}"
    request_payload = {
        "expected_version": expected_version,
        "reason": reason,
        "instructions": instructions,
        "snooze_until": snooze_until.isoformat() if snooze_until else None,
    }
    request_hash = hashlib.sha256(
        json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with get_connection() as conn:
        prior = conn.execute(
            """SELECT request_hash, response FROM idempotency_records
               WHERE workspace_id = %s AND operation = %s AND idempotency_key = %s""",
            (workspace_id, operation, idempotency_key),
        ).fetchone()
        if prior:
            if prior[0] != request_hash:
                raise IdempotencyConflictError(
                    "idempotency key was already used with another request"
                )
            return prior[1]

        row = conn.execute(
            """SELECT status, version, data FROM migrations
               WHERE workspace_id = %s AND id = %s FOR UPDATE""",
            (workspace_id, migration_id),
        ).fetchone()
        if not row:
            raise NotFoundError(migration_id)
        status, version, data = row
        new_status = ACTION_STATES[action]
        new_version = validate_transition(
            MIGRATION_TRANSITIONS,
            status,
            new_status,
            version=version,
            expected_version=expected_version,
        )
        now = datetime.now(UTC)
        new_attempt_id = None
        if action == "revise":
            previous = conn.execute(
                """SELECT id, number FROM migration_attempts
                   WHERE workspace_id = %s AND migration_id = %s
                   ORDER BY number DESC LIMIT 1""",
                (workspace_id, migration_id),
            ).fetchone()
            previous_id, previous_number = previous if previous else (None, 0)
            new_attempt_id = str(uuid.uuid4())
            attempt_data = {
                "id": new_attempt_id,
                "migration_id": migration_id,
                "number": previous_number + 1,
                "status": "created",
                "recommendation": None,
                "previous_attempt_id": previous_id,
                "evidence": None,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
            conn.execute(
                """INSERT INTO migration_attempts
                   (id, workspace_id, migration_id, number, previous_attempt_id,
                    idempotency_key, status, data)
                   VALUES (%s, %s, %s, %s, %s, %s, 'created', %s)""",
                (
                    new_attempt_id,
                    workspace_id,
                    migration_id,
                    previous_number + 1,
                    previous_id,
                    idempotency_key,
                    json.dumps(attempt_data),
                ),
            )
        updated = {
            **data,
            "status": new_status,
            "decision_state": action,
            "snoozed_until": snooze_until.isoformat() if snooze_until else None,
            "version": new_version,
            "current_attempt_id": new_attempt_id or data.get("current_attempt_id"),
            "updated_at": now.isoformat(),
        }
        decision_id = str(uuid.uuid4())
        conn.execute(
            """UPDATE migrations SET status = %s, version = %s, data = %s,
               current_attempt_id = %s, snoozed_until = %s, updated_at = %s
               WHERE workspace_id = %s AND id = %s AND version = %s""",
            (
                new_status,
                new_version,
                json.dumps(updated),
                updated["current_attempt_id"],
                snooze_until,
                now,
                workspace_id,
                migration_id,
                version,
            ),
        )
        conn.execute(
            """INSERT INTO developer_decisions
               (id, workspace_id, migration_id, action, actor, target_version, reason, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                decision_id,
                workspace_id,
                migration_id,
                action,
                actor,
                version,
                reason,
                json.dumps({"instructions": instructions} if instructions else {}),
            ),
        )
        audit_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO audit_events
               (id, workspace_id, actor, action, entity_type, entity_id, metadata, data)
               VALUES (%s, %s, %s, %s, 'migration', %s, %s, %s)""",
            (
                audit_id,
                workspace_id,
                actor,
                action,
                migration_id,
                json.dumps({"decision_id": decision_id, "from": status, "to": new_status}),
                json.dumps(
                    {
                        "id": audit_id,
                        "actor": actor,
                        "action": action,
                        "entity_type": "migration",
                        "entity_id": migration_id,
                        "metadata": {"decision_id": decision_id, "from": status, "to": new_status},
                        "created_at": now.isoformat(),
                    }
                ),
            ),
        )
        conn.execute(
            """INSERT INTO idempotency_records
               (workspace_id, operation, idempotency_key, request_hash, response)
               VALUES (%s, %s, %s, %s, %s)""",
            (workspace_id, operation, idempotency_key, request_hash, json.dumps(updated)),
        )
    return updated
