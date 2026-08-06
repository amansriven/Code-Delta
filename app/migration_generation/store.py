"""Durable orchestration state for migration generation attempts."""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.control_plane.models import ImpactEvidence, MigrationEvidence, NormalizedChange
from app.control_plane.state import (
    ATTEMPT_TRANSITIONS,
    MIGRATION_TRANSITIONS,
    StateTransitionError,
    validate_transition,
)
from app.control_plane.store import IdempotencyConflictError, NotFoundError
from app.db import get_connection
from app.repository_intelligence.models import RepositoryRef, RepositorySnapshot


@dataclass(frozen=True)
class AttemptContext:
    workspace_id: str
    migration_id: str
    attempt_id: str
    previous_attempt_id: str | None
    developer_instructions: str | None
    repository: RepositoryRef
    snapshot: RepositorySnapshot
    change: NormalizedChange
    impact: ImpactEvidence


def _request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _audit(
    conn,
    workspace_id: str,
    *,
    actor: str,
    action: str,
    migration_id: str,
    metadata: dict[str, Any],
    now: datetime,
) -> None:
    audit_id = str(uuid.uuid4())
    data = {
        "id": audit_id,
        "actor": actor,
        "action": action,
        "entity_type": "migration",
        "entity_id": migration_id,
        "metadata": metadata,
        "created_at": now.isoformat(),
    }
    conn.execute(
        """INSERT INTO audit_events
           (id, workspace_id, actor, action, entity_type, entity_id, metadata, data,
            created_at)
           VALUES (%s, %s, %s, %s, 'migration', %s, %s, %s, %s)""",
        (
            audit_id,
            workspace_id,
            actor,
            action,
            migration_id,
            json.dumps(metadata),
            json.dumps(data),
            now,
        ),
    )


def queue_attempt(
    workspace_id: str,
    migration_id: str,
    *,
    actor: str,
    expected_version: int,
    idempotency_key: str,
) -> dict[str, Any]:
    """Create or reuse a revision attempt and atomically move it to planning."""
    operation = f"migration:{migration_id}:generate"
    request_hash = _request_hash({"expected_version": expected_version})
    now = datetime.now(UTC)
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
            """SELECT status, version, current_attempt_id, data FROM migrations
               WHERE workspace_id = %s AND id = %s FOR UPDATE""",
            (workspace_id, migration_id),
        ).fetchone()
        if not row:
            raise NotFoundError(migration_id)
        status, version, current_attempt_id, migration_data = row
        next_migration_version = validate_transition(
            MIGRATION_TRANSITIONS,
            status,
            "planning",
            version=version,
            expected_version=expected_version,
        )

        attempt = None
        if current_attempt_id:
            attempt = conn.execute(
                """SELECT id, number, previous_attempt_id, status, version, data
                   FROM migration_attempts
                   WHERE workspace_id = %s AND migration_id = %s AND id = %s
                   FOR UPDATE""",
                (workspace_id, migration_id, current_attempt_id),
            ).fetchone()
        if attempt and attempt[3] == "created":
            (
                attempt_id,
                number,
                previous_attempt_id,
                attempt_status,
                attempt_version,
                attempt_data,
            ) = attempt
        else:
            latest = conn.execute(
                """SELECT COALESCE(MAX(number), 0) FROM migration_attempts
                   WHERE workspace_id = %s AND migration_id = %s""",
                (workspace_id, migration_id),
            ).fetchone()
            number = latest[0] + 1
            previous_attempt_id = current_attempt_id
            attempt_id = str(uuid.uuid4())
            attempt_status = "created"
            attempt_version = 1
            attempt_data = {
                "id": attempt_id,
                "migration_id": migration_id,
                "number": number,
                "status": "created",
                "recommendation": None,
                "previous_attempt_id": previous_attempt_id,
                "evidence": None,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
            conn.execute(
                """INSERT INTO migration_attempts
                   (id, workspace_id, migration_id, number, previous_attempt_id,
                    idempotency_key, status, version, data, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, 'created', 1, %s, %s, %s)""",
                (
                    attempt_id,
                    workspace_id,
                    migration_id,
                    number,
                    previous_attempt_id,
                    idempotency_key,
                    json.dumps(attempt_data),
                    now,
                    now,
                ),
            )

        next_attempt_version = validate_transition(
            ATTEMPT_TRANSITIONS,
            attempt_status,
            "planning",
            version=attempt_version,
            expected_version=attempt_version,
        )
        attempt_data = {
            **attempt_data,
            "status": "planning",
            "version": next_attempt_version,
            "updated_at": now.isoformat(),
        }
        migration_data = {
            **migration_data,
            "status": "planning",
            "decision_state": None,
            "current_attempt_id": attempt_id,
            "version": next_migration_version,
            "updated_at": now.isoformat(),
        }
        conn.execute(
            """UPDATE migration_attempts SET status = 'planning', version = %s, data = %s,
               updated_at = %s WHERE workspace_id = %s AND id = %s""",
            (
                next_attempt_version,
                json.dumps(attempt_data),
                now,
                workspace_id,
                attempt_id,
            ),
        )
        conn.execute(
            """UPDATE migrations SET status = 'planning', version = %s,
               current_attempt_id = %s, data = %s, updated_at = %s
               WHERE workspace_id = %s AND id = %s AND version = %s""",
            (
                next_migration_version,
                attempt_id,
                json.dumps(migration_data),
                now,
                workspace_id,
                migration_id,
                version,
            ),
        )
        response = {
            "migration_id": migration_id,
            "attempt_id": attempt_id,
            "status": "planning",
            "version": next_migration_version,
        }
        _audit(
            conn,
            workspace_id,
            actor=actor,
            action="migration.generation_queued",
            migration_id=migration_id,
            metadata={"attempt_id": attempt_id, "from": status, "to": "planning"},
            now=now,
        )
        conn.execute(
            """INSERT INTO idempotency_records
               (workspace_id, operation, idempotency_key, request_hash, response)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                workspace_id,
                operation,
                idempotency_key,
                request_hash,
                json.dumps(response),
            ),
        )
    return response


def claim_attempt(workspace_id: str, attempt_id: str) -> AttemptContext | None:
    """Claim one planning attempt and load its immutable analysis inputs."""
    with get_connection() as conn:
        claimed = conn.execute(
            """UPDATE migration_attempts SET status = 'generating', version = version + 1,
               data = data || jsonb_build_object(
                 'status', 'generating', 'version', version + 1,
                 'updated_at', now()::text
               ), updated_at = now()
               WHERE workspace_id = %s AND id = %s AND status = 'planning'
               RETURNING migration_id, previous_attempt_id, data""",
            (workspace_id, attempt_id),
        ).fetchone()
        if not claimed:
            return None
        migration_id, previous_attempt_id, attempt_data = claimed
        migration = conn.execute(
            """UPDATE migrations SET status = 'generating', version = version + 1,
               data = data || jsonb_build_object(
                 'status', 'generating', 'version', version + 1,
                 'updated_at', now()::text
               ), updated_at = now()
               WHERE workspace_id = %s AND id = %s AND current_attempt_id = %s
                 AND status = 'planning'
               RETURNING change_event_id, repository_id""",
            (workspace_id, migration_id, attempt_id),
        ).fetchone()
        if not migration:
            raise StateTransitionError("migration no longer owns the generation attempt")
        change_event_id, repository_id = migration
        row = conn.execute(
            """SELECT r.full_name, r.clone_url, r.default_branch, r.installation_id,
                      c.data, i.data, s.data
               FROM repositories r
               JOIN change_events c
                 ON c.workspace_id = r.workspace_id AND c.id = %s
               JOIN LATERAL (
                 SELECT data, snapshot_digest FROM impact_assessments
                 WHERE workspace_id = r.workspace_id AND repository_id = r.id
                   AND change_event_id = %s AND status = 'affected'
                 ORDER BY created_at DESC, id DESC LIMIT 1
               ) i ON TRUE
               JOIN repository_snapshots s
                 ON s.workspace_id = r.workspace_id AND s.repository_id = r.id
                AND s.content_digest = i.snapshot_digest
               WHERE r.workspace_id = %s AND r.id = %s AND r.enabled = TRUE
               ORDER BY s.created_at DESC LIMIT 1""",
            (change_event_id, change_event_id, workspace_id, repository_id),
        ).fetchone()
    if not row:
        raise NotFoundError("migration generation inputs are unavailable")
    (
        full_name,
        clone_url,
        default_branch,
        installation_id,
        change_data,
        impact_data,
        snapshot_data,
    ) = row
    if not clone_url or not installation_id:
        raise ValueError("repository_missing_checkout_metadata")
    normalized_fields = NormalizedChange.model_fields
    return AttemptContext(
        workspace_id=workspace_id,
        migration_id=migration_id,
        attempt_id=attempt_id,
        previous_attempt_id=previous_attempt_id,
        developer_instructions=attempt_data.get("developer_instructions"),
        repository=RepositoryRef(
            id=repository_id,
            workspace_id=workspace_id,
            full_name=full_name,
            clone_url=clone_url,
            default_branch=default_branch,
            installation_id=installation_id,
        ),
        snapshot=RepositorySnapshot.model_validate(snapshot_data),
        change=NormalizedChange.model_validate(
            {key: value for key, value in change_data.items() if key in normalized_fields}
        ),
        impact=ImpactEvidence.model_validate(impact_data),
    )


def complete_attempt(
    context: AttemptContext,
    evidence: MigrationEvidence,
    patch_object_ref: str,
) -> None:
    if evidence.attempt_id != context.attempt_id or evidence.migration_id != context.migration_id:
        raise ValueError("generation evidence does not match its attempt")
    checks_passed = all(check.status == "passed" for check in evidence.verification_checks)
    target = {
        "approve": "ready",
        "revise": "needs_revision",
        "snooze": "blocked",
        "decline": "blocked",
    }[evidence.recommendation.action]
    if target == "ready" and not checks_passed:
        raise ValueError("migration cannot become ready without passing verification")
    now = datetime.now(UTC)
    evidence_data = evidence.model_dump(mode="json")
    with get_connection() as conn:
        attempt = conn.execute(
            """SELECT status, version, data FROM migration_attempts
               WHERE workspace_id = %s AND id = %s FOR UPDATE""",
            (context.workspace_id, context.attempt_id),
        ).fetchone()
        migration = conn.execute(
            """SELECT status, version, data FROM migrations
               WHERE workspace_id = %s AND id = %s AND current_attempt_id = %s FOR UPDATE""",
            (context.workspace_id, context.migration_id, context.attempt_id),
        ).fetchone()
        if not attempt or not migration:
            raise NotFoundError(context.attempt_id)
        attempt_status, attempt_version, attempt_data = attempt
        migration_status, migration_version, migration_data = migration
        if attempt_status != "generating" or migration_status != "generating":
            raise StateTransitionError("generation attempt is no longer active")
        if target not in MIGRATION_TRANSITIONS["verifying"]:
            raise StateTransitionError("invalid generation result transition")

        artifact_id = evidence.patch.artifact_id
        artifact_data = {
            "id": artifact_id,
            "attempt_id": context.attempt_id,
            "kind": "structured_patch",
            "sha256": evidence.patch.sha256,
            "object_ref": patch_object_ref,
            "created_at": now.isoformat(),
        }
        conn.execute(
            """INSERT INTO migration_artifacts
               (id, workspace_id, attempt_id, kind, sha256, object_ref, data, created_at)
               VALUES (%s, %s, %s, 'structured_patch', %s, %s, %s, %s)
               ON CONFLICT (workspace_id, attempt_id, kind, sha256) DO NOTHING""",
            (
                artifact_id,
                context.workspace_id,
                context.attempt_id,
                evidence.patch.sha256,
                patch_object_ref,
                json.dumps(artifact_data),
                now,
            ),
        )
        final_attempt_version = attempt_version + 3
        attempt_data = {
            **attempt_data,
            "status": "completed",
            "version": final_attempt_version,
            "recommendation": evidence.recommendation.action,
            "evidence": evidence_data,
            "updated_at": now.isoformat(),
        }
        final_migration_version = migration_version + 2
        migration_data = {
            **migration_data,
            "status": target,
            "decision_state": None,
            "version": final_migration_version,
            "updated_at": now.isoformat(),
        }
        conn.execute(
            """UPDATE migration_attempts SET status = 'completed', version = %s, data = %s,
               updated_at = %s WHERE workspace_id = %s AND id = %s""",
            (
                final_attempt_version,
                json.dumps(attempt_data),
                now,
                context.workspace_id,
                context.attempt_id,
            ),
        )
        conn.execute(
            """UPDATE migrations SET status = %s, version = %s, data = %s,
               updated_at = %s WHERE workspace_id = %s AND id = %s""",
            (
                target,
                final_migration_version,
                json.dumps(migration_data),
                now,
                context.workspace_id,
                context.migration_id,
            ),
        )
        _audit(
            conn,
            context.workspace_id,
            actor="migration-generation-worker",
            action="migration.generation_completed",
            migration_id=context.migration_id,
            metadata={
                "attempt_id": context.attempt_id,
                "recommendation": evidence.recommendation.action,
                "status": target,
                "patch_sha256": evidence.patch.sha256,
            },
            now=now,
        )


def fail_attempt(workspace_id: str, attempt_id: str, error_code: str) -> None:
    safe_code = re.sub(r"[^a-z0-9_.-]", "_", error_code.lower())[:120] or "generation_failed"
    now = datetime.now(UTC)
    with get_connection() as conn:
        row = conn.execute(
            """SELECT migration_id, status, version, data FROM migration_attempts
               WHERE workspace_id = %s AND id = %s FOR UPDATE""",
            (workspace_id, attempt_id),
        ).fetchone()
        if not row:
            return
        migration_id, attempt_status, attempt_version, attempt_data = row
        if "failed" not in ATTEMPT_TRANSITIONS.get(attempt_status, frozenset()):
            return
        attempt_data = {
            **attempt_data,
            "status": "failed",
            "version": attempt_version + 1,
            "error_code": safe_code,
            "updated_at": now.isoformat(),
        }
        conn.execute(
            """UPDATE migration_attempts SET status = 'failed', version = version + 1,
               data = %s, updated_at = %s WHERE workspace_id = %s AND id = %s""",
            (json.dumps(attempt_data), now, workspace_id, attempt_id),
        )
        migration = conn.execute(
            """SELECT status, version, data FROM migrations
               WHERE workspace_id = %s AND id = %s AND current_attempt_id = %s FOR UPDATE""",
            (workspace_id, migration_id, attempt_id),
        ).fetchone()
        if migration and "blocked" in MIGRATION_TRANSITIONS.get(migration[0], frozenset()):
            migration_data = {
                **migration[2],
                "status": "blocked",
                "version": migration[1] + 1,
                "error_code": safe_code,
                "updated_at": now.isoformat(),
            }
            conn.execute(
                """UPDATE migrations SET status = 'blocked', version = version + 1,
                   data = %s, updated_at = %s WHERE workspace_id = %s AND id = %s""",
                (json.dumps(migration_data), now, workspace_id, migration_id),
            )
        _audit(
            conn,
            workspace_id,
            actor="migration-generation-worker",
            action="migration.generation_failed",
            migration_id=migration_id,
            metadata={"attempt_id": attempt_id, "error_code": safe_code},
            now=now,
        )
