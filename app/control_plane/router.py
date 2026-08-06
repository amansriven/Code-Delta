"""Workspace-scoped Phase 1 control-plane HTTP API."""

import os
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.control_plane import store
from app.control_plane.models import DeveloperActionRequest
from app.control_plane.state import StateTransitionError, VersionConflictError
from app.oauth import FRONTEND_URL, get_session

router = APIRouter(tags=["control-plane"])

LIST_COLUMNS = {
    "changes": ("change_events", ["id", "data", "created_at"]),
    "migrations": ("migrations", ["id", "data", "created_at"]),
    "providers": ("providers", ["id", "data", "created_at"]),
    "repositories": ("repositories", ["id", "data", "created_at"]),
    "audit-events": ("audit_events", ["id", "data", "created_at"]),
}


def _workspace(session: Annotated[dict, Depends(get_session)]) -> tuple[str, dict]:
    return store.ensure_workspace(session), session


def _page(resource: str, workspace_id: str, cursor: str | None, limit: int) -> dict:
    table, columns = LIST_COLUMNS[resource]
    try:
        rows, next_cursor = store.list_records(
            workspace_id, table, columns, cursor=cursor, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": [row["data"] for row in rows], "next_cursor": next_cursor}


@router.get("/changes")
def list_changes(
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return _page("changes", context[0], cursor, limit)


@router.get("/changes/{change_id}")
def get_change(change_id: str, context: Annotated[tuple[str, dict], Depends(_workspace)]):
    try:
        return store.get_record(context[0], "change_events", change_id)
    except store.NotFoundError as exc:
        raise HTTPException(status_code=404, detail="change not found") from exc


@router.get("/migrations")
def list_migrations(
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return _page("migrations", context[0], cursor, limit)


@router.get("/migrations/{migration_id}")
def get_migration(
    migration_id: str, context: Annotated[tuple[str, dict], Depends(_workspace)]
):
    try:
        return store.get_migration(context[0], migration_id)
    except store.NotFoundError as exc:
        raise HTTPException(status_code=404, detail="migration not found") from exc


@router.get("/migrations/{migration_id}/attempts/{attempt_id}")
def get_attempt(
    migration_id: str,
    attempt_id: str,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
):
    try:
        attempt = store.get_record(context[0], "migration_attempts", attempt_id)
    except store.NotFoundError as exc:
        raise HTTPException(status_code=404, detail="attempt not found") from exc
    if attempt.get("migration_id") != migration_id:
        raise HTTPException(status_code=404, detail="attempt not found")
    return attempt


@router.get("/providers")
def list_providers(
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return _page("providers", context[0], cursor, limit)


@router.get("/repositories")
def list_repositories(
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return _page("repositories", context[0], cursor, limit)


@router.get("/audit-events")
def list_audit_events(
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return _page("audit-events", context[0], cursor, limit)


def _require_trusted_origin(request: Request) -> None:
    """Use the browser Origin header as the session cookie's CSRF boundary."""
    origin = request.headers.get("origin")
    trusted = urlparse(FRONTEND_URL)
    candidate = urlparse(origin) if origin else None
    if not candidate or (candidate.scheme, candidate.netloc) != (trusted.scheme, trusted.netloc):
        raise HTTPException(status_code=403, detail="untrusted mutation origin")


def _developer_action(
    migration_id: str,
    action: str,
    body: DeveloperActionRequest,
    request: Request,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
):
    _require_trusted_origin(request)
    if action in {"revise", "decline"} and not body.reason:
        raise HTTPException(status_code=422, detail="reason is required for this action")
    if action == "revise" and not body.instructions:
        raise HTTPException(status_code=422, detail="instructions are required for revision")
    if action == "snooze" and body.snooze_until is None:
        raise HTTPException(status_code=422, detail="snooze_until is required")
    workspace_id, session = context
    try:
        if (
            action in {"approve", "decline"}
            and os.environ.get("GITHUB_PUBLISHING_ENABLED", "").lower() == "true"
        ):
            from app.github_publishing.actions import synchronize_developer_action

            synchronize_developer_action(
                workspace_id,
                migration_id,
                action,
                actor=session["github_login"],
                expected_version=body.expected_version,
            )
        return store.apply_developer_action(
            workspace_id,
            migration_id,
            action,
            actor=session["github_login"],
            expected_version=body.expected_version,
            idempotency_key=idempotency_key,
            reason=body.reason,
            instructions=body.instructions,
            snooze_until=body.snooze_until,
        )
    except store.NotFoundError as exc:
        raise HTTPException(status_code=404, detail="migration not found") from exc
    except VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except store.IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail="GitHub pull request update failed") from exc


@router.post("/migrations/{migration_id}/approve")
def approve_migration(
    migration_id: str,
    body: DeveloperActionRequest,
    request: Request,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
):
    return _developer_action(
        migration_id, "approve", body, request, context, idempotency_key
    )


@router.post("/migrations/{migration_id}/revise")
def revise_migration(
    migration_id: str,
    body: DeveloperActionRequest,
    request: Request,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
):
    return _developer_action(
        migration_id, "revise", body, request, context, idempotency_key
    )


@router.post("/migrations/{migration_id}/snooze")
def snooze_migration(
    migration_id: str,
    body: DeveloperActionRequest,
    request: Request,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
):
    return _developer_action(
        migration_id, "snooze", body, request, context, idempotency_key
    )


@router.post("/migrations/{migration_id}/decline")
def decline_migration(
    migration_id: str,
    body: DeveloperActionRequest,
    request: Request,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
):
    return _developer_action(
        migration_id, "decline", body, request, context, idempotency_key
    )
