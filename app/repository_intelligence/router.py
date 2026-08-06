"""Workspace-scoped repository intelligence read API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.control_plane.store import NotFoundError, ensure_workspace
from app.oauth import get_session
from app.repository_intelligence import store

router = APIRouter(tags=["repository-intelligence"])


def _workspace(session: Annotated[dict, Depends(get_session)]) -> str:
    return ensure_workspace(session)


@router.get("/repositories/{repository_id}/snapshots")
def list_repository_snapshots(
    repository_id: str,
    workspace_id: Annotated[str, Depends(_workspace)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
):
    try:
        items, next_cursor = store.list_repository_snapshots(
            workspace_id, repository_id, cursor=cursor, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": items, "next_cursor": next_cursor}


@router.get("/changes/{change_id}/impacts")
def list_change_impacts(
    change_id: str,
    workspace_id: Annotated[str, Depends(_workspace)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
):
    try:
        items, next_cursor = store.list_change_impacts(
            workspace_id, change_id, cursor=cursor, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": items, "next_cursor": next_cursor}


@router.get("/impact-assessments/{assessment_id}")
def get_impact(
    assessment_id: str,
    workspace_id: Annotated[str, Depends(_workspace)],
):
    try:
        return store.get_impact(workspace_id, assessment_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="impact assessment not found") from exc
