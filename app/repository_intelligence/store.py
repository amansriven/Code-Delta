"""PostgreSQL lifecycle and read models for repository intelligence."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.control_plane.models import MigrationSummary, NormalizedChange
from app.control_plane.store import NotFoundError, _decode_cursor, _encode_cursor
from app.db import get_connection
from app.repository_intelligence.models import RepositoryAnalysisResult, RepositoryRef


@dataclass(frozen=True)
class FanoutJobContext:
    id: str
    workspace_id: str
    repository: RepositoryRef
    change: NormalizedChange


def queued_fanout_job_ids(workspace_id: str, change_event_ids: list[str]) -> list[str]:
    if not change_event_ids:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id FROM change_fanout_jobs
               WHERE workspace_id = %s AND change_event_id = ANY(%s) AND status = 'queued'
               ORDER BY created_at, id""",
            (workspace_id, change_event_ids),
        ).fetchall()
    return [row[0] for row in rows]


def claim_fanout_job(workspace_id: str, job_id: str) -> FanoutJobContext | None:
    """Atomically claim one queued job and load its immutable input contracts."""
    with get_connection() as conn:
        claimed = conn.execute(
            """UPDATE change_fanout_jobs SET status = 'analyzing', error_code = NULL,
               updated_at = now()
               WHERE workspace_id = %s AND id = %s AND status = 'queued'
               RETURNING change_event_id, repository_id""",
            (workspace_id, job_id),
        ).fetchone()
        if not claimed:
            return None
        change_id, repository_id = claimed
        row = conn.execute(
            """SELECT r.full_name, r.clone_url, r.default_branch, r.installation_id, c.data
               FROM repositories r
               JOIN change_events c
                 ON c.workspace_id = r.workspace_id AND c.id = %s
               WHERE r.workspace_id = %s AND r.id = %s AND r.enabled = TRUE""",
            (change_id, workspace_id, repository_id),
        ).fetchone()
    if not row:
        raise NotFoundError("fanout job repository or change is unavailable")
    full_name, clone_url, default_branch, installation_id, change_data = row
    if not clone_url or not installation_id:
        raise ValueError("repository_missing_checkout_metadata")
    normalized_fields = NormalizedChange.model_fields
    normalized_change = NormalizedChange.model_validate(
        {key: value for key, value in change_data.items() if key in normalized_fields}
    )
    repository = RepositoryRef(
        id=repository_id,
        workspace_id=workspace_id,
        full_name=full_name,
        clone_url=clone_url,
        default_branch=default_branch,
        installation_id=installation_id,
    )
    return FanoutJobContext(
        id=job_id,
        workspace_id=workspace_id,
        repository=repository,
        change=normalized_change,
    )


def complete_fanout_job(context: FanoutJobContext, result: RepositoryAnalysisResult) -> None:
    """Persist snapshot, evidence, and an affected migration in one transaction."""
    snapshot = result.snapshot
    inventory = result.inventory
    impact = result.impact
    if (
        snapshot.repository_id != context.repository.id
        or inventory.repository_id != context.repository.id
        or inventory.commit_sha != snapshot.commit_sha
        or inventory.workspace_digest != snapshot.content_digest
        or inventory.inventory_digest != snapshot.inventory_digest
    ):
        raise ValueError("repository analysis result does not match its fanout job")
    now = datetime.now(UTC)
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO repository_snapshots
               (id, workspace_id, repository_id, commit_sha, content_digest,
                inventory_digest, inventory_version, inventory, data, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (workspace_id, repository_id, content_digest, inventory_digest)
               DO NOTHING""",
            (
                snapshot.id,
                context.workspace_id,
                context.repository.id,
                snapshot.commit_sha,
                snapshot.content_digest,
                snapshot.inventory_digest,
                snapshot.inventory_version,
                json.dumps(inventory.model_dump(mode="json")),
                json.dumps(snapshot.model_dump(mode="json")),
                snapshot.created_at,
            ),
        )
        for dependency in inventory.dependencies:
            conn.execute(
                """INSERT INTO repository_dependencies
                   (workspace_id, snapshot_id, dependency_id, ecosystem, package, data)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    context.workspace_id,
                    snapshot.id,
                    dependency.id,
                    dependency.ecosystem,
                    dependency.package,
                    json.dumps(dependency.model_dump(mode="json")),
                ),
            )
        conn.execute(
            """INSERT INTO impact_assessments
               (id, workspace_id, change_event_id, repository_id, snapshot_digest,
                status, capability_report, data, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (workspace_id, change_event_id, repository_id, snapshot_digest)
               DO NOTHING""",
            (
                impact.assessment_id,
                context.workspace_id,
                context.change.id,
                context.repository.id,
                snapshot.content_digest,
                impact.conclusion,
                json.dumps(impact.coverage.model_dump(mode="json")),
                json.dumps(impact.model_dump(mode="json")),
                now,
                now,
            ),
        )
        for call_site in impact.call_sites:
            conn.execute(
                """INSERT INTO repository_call_sites
                   (workspace_id, assessment_id, call_site_id, snapshot_id, path, data)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    context.workspace_id,
                    impact.assessment_id,
                    call_site.id,
                    snapshot.id,
                    call_site.path,
                    json.dumps(call_site.model_dump(mode="json")),
                ),
            )
        if impact.conclusion == "affected":
            _create_migration(conn, context, impact.assessment_id, now)
        conn.execute(
            """UPDATE change_fanout_jobs SET status = 'completed', error_code = NULL,
               updated_at = %s WHERE workspace_id = %s AND id = %s AND status = 'analyzing'""",
            (now, context.workspace_id, context.id),
        )


def _create_migration(conn, context: FanoutJobContext, assessment_id: str, now: datetime) -> None:
    migration_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"migration:{context.workspace_id}:{context.change.id}:{context.repository.id}",
        )
    )
    migration = MigrationSummary(
        id=migration_id,
        change_event_id=context.change.id,
        repository_id=context.repository.id,
        repository_full_name=context.repository.full_name,
        provider_name=context.change.provider.name,
        change_summary=context.change.summary,
        risk=context.change.severity,
        status="queued",
        version=1,
        created_at=now,
        updated_at=now,
    )
    inserted = conn.execute(
        """INSERT INTO migrations
           (id, workspace_id, change_event_id, repository_id, status, data, created_at, updated_at)
           VALUES (%s, %s, %s, %s, 'queued', %s, %s, %s)
           ON CONFLICT DO NOTHING RETURNING id""",
        (
            migration_id,
            context.workspace_id,
            context.change.id,
            context.repository.id,
            json.dumps(migration.model_dump(mode="json")),
            now,
            now,
        ),
    ).fetchone()
    if not inserted:
        return
    audit_id = str(uuid.uuid4())
    audit_data = {
        "id": audit_id,
        "actor": "repository-intelligence-worker",
        "action": "migration.queued",
        "entity_type": "migration",
        "entity_id": migration_id,
        "metadata": {"impact_assessment_id": assessment_id},
        "created_at": now.isoformat(),
    }
    conn.execute(
        """INSERT INTO audit_events
           (id, workspace_id, actor, action, entity_type, entity_id, metadata, data, created_at)
           VALUES (%s, %s, %s, %s, 'migration', %s, %s, %s, %s)""",
        (
            audit_id,
            context.workspace_id,
            "repository-intelligence-worker",
            "migration.queued",
            migration_id,
            json.dumps({"impact_assessment_id": assessment_id}),
            json.dumps(audit_data),
            now,
        ),
    )


def fail_fanout_job(workspace_id: str, job_id: str, error_code: str) -> None:
    safe_code = error_code[:120]
    with get_connection() as conn:
        conn.execute(
            """UPDATE change_fanout_jobs SET status = 'failed', error_code = %s,
               updated_at = now()
               WHERE workspace_id = %s AND id = %s AND status = 'analyzing'""",
            (safe_code, workspace_id, job_id),
        )


def _list_evidence(
    workspace_id: str,
    table: str,
    scope_column: str,
    scope_id: str,
    *,
    cursor: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None]:
    if (table, scope_column) not in {
        ("repository_snapshots", "repository_id"),
        ("impact_assessments", "change_event_id"),
    }:
        raise ValueError("unsupported repository intelligence resource")
    position = _decode_cursor(cursor)
    where = f"workspace_id = %s AND {scope_column} = %s"
    params: list[Any] = [workspace_id, scope_id]
    if position:
        where += " AND (created_at, id::text) < (%s, %s)"
        params.extend(position)
    params.append(limit + 1)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id, data, created_at FROM {table} WHERE {where} "  # noqa: S608
            "ORDER BY created_at DESC, id::text DESC LIMIT %s",
            params,
        ).fetchall()
    page = rows[:limit]
    next_cursor = _encode_cursor(page[-1][2], page[-1][0]) if len(rows) > limit and page else None
    return [row[1] for row in page], next_cursor


def list_repository_snapshots(
    workspace_id: str, repository_id: str, *, cursor: str | None, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    return _list_evidence(
        workspace_id,
        "repository_snapshots",
        "repository_id",
        repository_id,
        cursor=cursor,
        limit=limit,
    )


def list_change_impacts(
    workspace_id: str, change_id: str, *, cursor: str | None, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    return _list_evidence(
        workspace_id,
        "impact_assessments",
        "change_event_id",
        change_id,
        cursor=cursor,
        limit=limit,
    )


def get_impact(workspace_id: str, assessment_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT data FROM impact_assessments
               WHERE workspace_id = %s AND id = %s""",
            (workspace_id, assessment_id),
        ).fetchone()
    if not row:
        raise NotFoundError(assessment_id)
    return row[0]
