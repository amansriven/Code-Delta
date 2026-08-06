"""Durable Phase 5 publication state and external-write audit trail."""

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, NamedTuple

from app.control_plane.models import MigrationEvidence
from app.control_plane.state import MIGRATION_TRANSITIONS, StateTransitionError, validate_transition
from app.control_plane.store import IdempotencyConflictError, NotFoundError
from app.db import get_connection
from app.repository_intelligence.models import RepositoryRef

from .models import PublicationContext, PublicationRecord, PublicationResult


class PullRequestActionContext(NamedTuple):
    repository_full_name: str
    installation_id: int
    pull_number: int
    pull_node_id: str
    head_sha: str


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _audit(conn, workspace_id: str, migration_id: str, action: str, metadata: dict) -> None:
    now = datetime.now(UTC)
    audit_id = str(uuid.uuid4())
    data = {
        "id": audit_id,
        "actor": "github-publisher",
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
           VALUES (%s, %s, 'github-publisher', %s, 'migration', %s, %s, %s, %s)""",
        (
            audit_id,
            workspace_id,
            action,
            migration_id,
            json.dumps(metadata),
            json.dumps(data),
            now,
        ),
    )


def _branch_name(migration_id: str) -> str:
    suffix = hashlib.sha256(migration_id.encode()).hexdigest()[:16]
    return f"delta-code/migration-{suffix}"


def queue_publication(
    workspace_id: str,
    migration_id: str,
    *,
    actor: str,
    expected_version: int,
    idempotency_key: str,
) -> dict[str, Any]:
    operation = f"migration:{migration_id}:publish"
    request_hash = _hash({"expected_version": expected_version})
    now = datetime.now(UTC)
    with get_connection() as conn:
        prior = conn.execute(
            """SELECT request_hash, response FROM idempotency_records
               WHERE workspace_id = %s AND operation = %s AND idempotency_key = %s""",
            (workspace_id, operation, idempotency_key),
        ).fetchone()
        if prior:
            if prior[0] != request_hash:
                raise IdempotencyConflictError("idempotency key was reused with another request")
            return prior[1]
        migration = conn.execute(
            """SELECT status, version, current_attempt_id, repository_id, data
               FROM migrations WHERE workspace_id = %s AND id = %s FOR UPDATE""",
            (workspace_id, migration_id),
        ).fetchone()
        if not migration:
            raise NotFoundError(migration_id)
        status, version, attempt_id, repository_id, migration_data = migration
        next_version = validate_transition(
            MIGRATION_TRANSITIONS,
            status,
            "pr_opening",
            version=version,
            expected_version=expected_version,
        )
        attempt = conn.execute(
            """SELECT status, data FROM migration_attempts
               WHERE workspace_id = %s AND id = %s AND migration_id = %s""",
            (workspace_id, attempt_id, migration_id),
        ).fetchone()
        if not attempt or attempt[0] != "completed":
            raise StateTransitionError("only a completed current attempt can be published")
        evidence = MigrationEvidence.model_validate(attempt[1].get("evidence"))
        if evidence.recommendation.action != "approve" or any(
            check.status != "passed" for check in evidence.verification_checks
        ):
            raise StateTransitionError("only an approved, fully verified attempt can be published")
        artifact = conn.execute(
            """SELECT object_ref FROM migration_artifacts
               WHERE workspace_id = %s AND attempt_id = %s AND id = %s
                 AND sha256 = %s AND kind = 'structured_patch'""",
            (workspace_id, attempt_id, evidence.patch.artifact_id, evidence.patch.sha256),
        ).fetchone()
        if not artifact:
            raise NotFoundError("validated patch artifact is unavailable")

        existing = conn.execute(
            """SELECT id, last_attempt_id, branch, remote_head_sha, pull_number,
                      pull_node_id, pull_url
               FROM pull_request_records
               WHERE workspace_id = %s AND migration_id = %s FOR UPDATE""",
            (workspace_id, migration_id),
        ).fetchone()
        if existing:
            publication_id, old_attempt, branch, remote_head, number, node_id, url = existing
            new_attempt = old_attempt != attempt_id
            conn.execute(
                """UPDATE pull_request_records SET last_attempt_id = %s, status = 'queued',
                   base_sha = %s, patch_sha256 = %s,
                   tree_sha = CASE WHEN %s THEN NULL ELSE tree_sha END,
                   commit_sha = CASE WHEN %s THEN NULL ELSE commit_sha END,
                   check_run_id = CASE WHEN %s THEN NULL ELSE check_run_id END,
                   error_code = NULL, updated_at = %s
                   WHERE workspace_id = %s AND id = %s""",
                (
                    attempt_id,
                    evidence.repository.base_commit_sha,
                    evidence.patch.sha256,
                    new_attempt,
                    new_attempt,
                    new_attempt,
                    now,
                    workspace_id,
                    publication_id,
                ),
            )
            del remote_head, number, node_id, url
        else:
            publication_id = str(uuid.uuid4())
            branch = _branch_name(migration_id)
            record_data = {
                "id": publication_id,
                "migration_id": migration_id,
                "last_attempt_id": attempt_id,
                "status": "queued",
                "branch": branch,
                "base_sha": evidence.repository.base_commit_sha,
                "patch_sha256": evidence.patch.sha256,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
            conn.execute(
                """INSERT INTO pull_request_records
                   (id, workspace_id, migration_id, repository_id, last_attempt_id,
                    status, branch, base_sha, patch_sha256, data, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, 'queued', %s, %s, %s, %s, %s, %s)""",
                (
                    publication_id,
                    workspace_id,
                    migration_id,
                    repository_id,
                    attempt_id,
                    branch,
                    evidence.repository.base_commit_sha,
                    evidence.patch.sha256,
                    json.dumps(record_data),
                    now,
                    now,
                ),
            )
        migration_data = {
            **migration_data,
            "status": "pr_opening",
            "version": next_version,
            "error_code": None,
            "updated_at": now.isoformat(),
        }
        conn.execute(
            """UPDATE migrations SET status = 'pr_opening', version = %s, data = %s,
               updated_at = %s WHERE workspace_id = %s AND id = %s AND version = %s""",
            (
                next_version,
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
            "publication_id": publication_id,
            "status": "queued",
            "version": next_version,
        }
        _audit(
            conn,
            workspace_id,
            migration_id,
            "github.publication_queued",
            {"attempt_id": attempt_id, "publication_id": publication_id, "actor": actor},
        )
        conn.execute(
            """INSERT INTO idempotency_records
               (workspace_id, operation, idempotency_key, request_hash, response)
               VALUES (%s, %s, %s, %s, %s)""",
            (workspace_id, operation, idempotency_key, request_hash, json.dumps(response)),
        )
    return response


def claim_publication(workspace_id: str, publication_id: str) -> PublicationContext | None:
    with get_connection() as conn:
        claimed = conn.execute(
            """UPDATE pull_request_records SET status = 'publishing', error_code = NULL,
               updated_at = now() WHERE workspace_id = %s AND id = %s AND status = 'queued'
               RETURNING migration_id, repository_id, last_attempt_id""",
            (workspace_id, publication_id),
        ).fetchone()
        if not claimed:
            return None
        migration_id, repository_id, attempt_id = claimed
        row = conn.execute(
            """SELECT r.full_name, r.clone_url, r.default_branch, r.installation_id,
                      a.data, p.id, p.status, p.branch, p.base_sha, p.patch_sha256,
                      p.tree_sha, p.commit_sha, p.remote_head_sha, p.pull_number,
                      p.pull_node_id, p.pull_url, p.check_run_id, ma.object_ref
               FROM repositories r
               JOIN migration_attempts a
                 ON a.workspace_id = r.workspace_id AND a.id = %s
               JOIN pull_request_records p
                 ON p.workspace_id = r.workspace_id AND p.id = %s
               JOIN migration_artifacts ma
                 ON ma.workspace_id = a.workspace_id AND ma.attempt_id = a.id
                AND ma.id = a.data->'evidence'->'patch'->>'artifact_id'
               WHERE r.workspace_id = %s AND r.id = %s AND r.enabled = TRUE""",
            (attempt_id, publication_id, workspace_id, repository_id),
        ).fetchone()
    if not row:
        raise NotFoundError("publication inputs are unavailable")
    (
        full_name,
        clone_url,
        default_branch,
        installation_id,
        attempt_data,
        record_id,
        record_status,
        branch,
        base_sha,
        patch_sha256,
        tree_sha,
        commit_sha,
        remote_head_sha,
        pull_number,
        pull_node_id,
        pull_url,
        check_run_id,
        object_ref,
    ) = row
    if not clone_url or not installation_id:
        raise ValueError("repository_missing_publisher_metadata")
    return PublicationContext(
        workspace_id=workspace_id,
        repository=RepositoryRef(
            id=repository_id,
            workspace_id=workspace_id,
            full_name=full_name,
            clone_url=clone_url,
            default_branch=default_branch,
            installation_id=installation_id,
        ),
        evidence=MigrationEvidence.model_validate(attempt_data.get("evidence")),
        artifact_object_ref=object_ref,
        record=PublicationRecord(
            id=record_id,
            migration_id=migration_id,
            last_attempt_id=attempt_id,
            status=record_status,
            branch=branch,
            base_sha=base_sha,
            patch_sha256=patch_sha256,
            tree_sha=tree_sha,
            commit_sha=commit_sha,
            remote_head_sha=remote_head_sha,
            pull_number=pull_number,
            pull_node_id=pull_node_id,
            pull_url=pull_url,
            check_run_id=check_run_id,
        ),
    )


class DatabasePublicationProgress:
    def __init__(self, context: PublicationContext) -> None:
        self.context = context

    def _record(self, fields: dict[str, Any], action: str, metadata: dict) -> None:
        allowed = {
            "tree_sha",
            "commit_sha",
            "remote_head_sha",
            "pull_number",
            "pull_node_id",
            "pull_url",
            "check_run_id",
        }
        if not fields or set(fields) - allowed:
            raise ValueError("invalid publication progress fields")
        assignments = ", ".join(f"{field} = %s" for field in fields)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE pull_request_records SET {assignments}, updated_at = now() "  # noqa: S608
                "WHERE workspace_id = %s AND id = %s AND status = 'publishing'",
                (*fields.values(), self.context.workspace_id, self.context.record.id),
            )
            _audit(
                conn,
                self.context.workspace_id,
                self.context.record.migration_id,
                action,
                {"publication_id": self.context.record.id, **metadata},
            )

    def record_tree(self, tree_sha: str) -> None:
        self._record({"tree_sha": tree_sha}, "github.tree.created", {"tree_sha": tree_sha})

    def record_commit(self, commit_sha: str) -> None:
        self._record(
            {"commit_sha": commit_sha}, "github.commit.created", {"commit_sha": commit_sha}
        )

    def record_branch(self, head_sha: str, action: str) -> None:
        self._record(
            {"remote_head_sha": head_sha},
            f"github.branch.{action}",
            {"branch": self.context.record.branch, "head_sha": head_sha},
        )

    def record_pull_request(self, number: int, node_id: str, url: str, action: str) -> None:
        self._record(
            {"pull_number": number, "pull_node_id": node_id, "pull_url": url},
            f"github.pull_request.{action}",
            {"number": number, "url": url},
        )

    def record_check(self, check_run_id: int) -> None:
        self._record(
            {"check_run_id": check_run_id},
            "github.check.created",
            {"check_run_id": check_run_id},
        )


def complete_publication(context: PublicationContext, result: PublicationResult) -> None:
    now = datetime.now(UTC)
    with get_connection() as conn:
        updated = conn.execute(
            """UPDATE pull_request_records SET status = 'completed', tree_sha = %s,
               commit_sha = %s, remote_head_sha = %s, pull_number = %s,
               pull_node_id = %s, pull_url = %s, check_run_id = %s,
               error_code = NULL, updated_at = %s
               WHERE workspace_id = %s AND id = %s AND status = 'publishing'
               RETURNING migration_id""",
            (
                result.tree_sha,
                result.commit_sha,
                result.commit_sha,
                result.pull_number,
                result.pull_node_id,
                result.pull_url,
                result.check_run_id,
                now,
                context.workspace_id,
                context.record.id,
            ),
        ).fetchone()
        if not updated:
            raise StateTransitionError("publication is no longer active")
        migration = conn.execute(
            """SELECT version, data FROM migrations WHERE workspace_id = %s AND id = %s
               AND current_attempt_id = %s AND status = 'pr_opening' FOR UPDATE""",
            (context.workspace_id, context.record.migration_id, context.record.last_attempt_id),
        ).fetchone()
        if not migration:
            raise StateTransitionError("migration no longer owns the publication")
        version, data = migration
        data = {
            **data,
            "status": "pr_opened",
            "version": version + 1,
            "pull_request_url": result.pull_url,
            "error_code": None,
            "updated_at": now.isoformat(),
        }
        conn.execute(
            """UPDATE migrations SET status = 'pr_opened', version = version + 1,
               data = %s, updated_at = %s WHERE workspace_id = %s AND id = %s""",
            (json.dumps(data), now, context.workspace_id, context.record.migration_id),
        )
        _audit(
            conn,
            context.workspace_id,
            context.record.migration_id,
            "github.publication_completed",
            {"publication_id": context.record.id, "pull_number": result.pull_number},
        )


def fail_publication(workspace_id: str, publication_id: str, error_code: str) -> None:
    safe = re.sub(r"[^a-z0-9_.-]", "_", error_code.lower())[:120] or "publication_failed"
    now = datetime.now(UTC)
    with get_connection() as conn:
        row = conn.execute(
            """UPDATE pull_request_records SET status = 'failed', error_code = %s,
               updated_at = %s WHERE workspace_id = %s AND id = %s
               AND status = 'publishing' RETURNING migration_id""",
            (safe, now, workspace_id, publication_id),
        ).fetchone()
        if not row:
            return
        migration_id = row[0]
        migration = conn.execute(
            """SELECT version, data FROM migrations WHERE workspace_id = %s AND id = %s
               AND status = 'pr_opening' FOR UPDATE""",
            (workspace_id, migration_id),
        ).fetchone()
        if migration:
            data = {
                **migration[1],
                "status": "blocked",
                "version": migration[0] + 1,
                "error_code": safe,
                "updated_at": now.isoformat(),
            }
            conn.execute(
                """UPDATE migrations SET status = 'blocked', version = version + 1,
                   data = %s, updated_at = %s WHERE workspace_id = %s AND id = %s""",
                (json.dumps(data), now, workspace_id, migration_id),
            )
        _audit(
            conn,
            workspace_id,
            migration_id,
            "github.publication_failed",
            {"publication_id": publication_id, "error_code": safe},
        )


def get_publication(workspace_id: str, migration_id: str) -> dict[str, Any]:
    columns = [
        "id",
        "migration_id",
        "last_attempt_id",
        "status",
        "branch",
        "base_sha",
        "patch_sha256",
        "tree_sha",
        "commit_sha",
        "remote_head_sha",
        "pull_number",
        "pull_node_id",
        "pull_url",
        "check_run_id",
        "error_code",
        "created_at",
        "updated_at",
    ]
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT {', '.join(columns)} FROM pull_request_records "  # noqa: S608
            "WHERE workspace_id = %s AND migration_id = %s",
            (workspace_id, migration_id),
        ).fetchone()
    if not row:
        raise NotFoundError(migration_id)
    return dict(zip(columns, row, strict=True))


def load_pull_request_action(
    workspace_id: str,
    migration_id: str,
    expected_version: int,
) -> PullRequestActionContext:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT r.full_name, r.installation_id, p.pull_number, p.pull_node_id,
                      p.remote_head_sha, m.status, m.version
               FROM migrations m
               JOIN repositories r
                 ON r.workspace_id = m.workspace_id AND r.id = m.repository_id
               JOIN pull_request_records p
                 ON p.workspace_id = m.workspace_id AND p.migration_id = m.id
               WHERE m.workspace_id = %s AND m.id = %s AND p.status = 'completed'""",
            (workspace_id, migration_id),
        ).fetchone()
    if not row:
        raise NotFoundError("published pull request is unavailable")
    full_name, installation_id, number, node_id, head_sha, status, version = row
    if version != expected_version:
        from app.control_plane.state import VersionConflictError

        raise VersionConflictError(f"expected version {expected_version}, found {version}")
    if status != "pr_opened" or not all((installation_id, number, node_id, head_sha)):
        raise StateTransitionError("migration does not have an actionable draft pull request")
    return PullRequestActionContext(full_name, installation_id, number, node_id, head_sha)


def migration_has_opened_pull_request(workspace_id: str, migration_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM migrations WHERE workspace_id = %s AND id = %s",
            (workspace_id, migration_id),
        ).fetchone()
    if not row:
        raise NotFoundError(migration_id)
    return row[0] == "pr_opened"


def audit_pull_request_action(
    workspace_id: str,
    migration_id: str,
    action: str,
    actor: str,
) -> None:
    with get_connection() as conn:
        _audit(
            conn,
            workspace_id,
            migration_id,
            f"github.pull_request.{action}",
            {"actor": actor},
        )
