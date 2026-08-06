"""Authenticated, explicitly gated GitHub publication API."""

import os
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.control_plane import store as control_plane_store
from app.control_plane.models import PublishMigrationRequest
from app.control_plane.state import StateTransitionError, VersionConflictError
from app.oauth import FRONTEND_URL, get_session

from . import store
from .tasks import publish_migration_draft

router = APIRouter(tags=["github-publishing"])


def _workspace(session: Annotated[dict, Depends(get_session)]) -> tuple[str, dict]:
    return control_plane_store.ensure_workspace(session), session


def _trusted_origin(request: Request) -> None:
    origin = urlparse(request.headers.get("origin") or "")
    expected = urlparse(FRONTEND_URL)
    if (origin.scheme, origin.netloc) != (expected.scheme, expected.netloc):
        raise HTTPException(status_code=403, detail="untrusted mutation origin")


@router.post(
    "/migrations/{migration_id}/publish",
    status_code=status.HTTP_202_ACCEPTED,
)
def publish_migration(
    migration_id: str,
    body: PublishMigrationRequest,
    request: Request,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=200),
    ],
):
    _trusted_origin(request)
    if os.environ.get("GITHUB_PUBLISHING_ENABLED", "").lower() != "true":
        raise HTTPException(status_code=503, detail="GitHub publishing is disabled")
    workspace_id, session = context
    try:
        response = store.queue_publication(
            workspace_id,
            migration_id,
            actor=session["github_login"],
            expected_version=body.expected_version,
            idempotency_key=idempotency_key,
        )
        publish_migration_draft.defer(
            workspace_id=workspace_id,
            publication_id=response["publication_id"],
        )
        return response
    except control_plane_store.NotFoundError as exc:
        raise HTTPException(status_code=404, detail="publication input not found") from exc
    except (VersionConflictError, StateTransitionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except control_plane_store.IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/migrations/{migration_id}/publication")
def publication_status(
    migration_id: str,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
):
    try:
        return store.get_publication(context[0], migration_id)
    except control_plane_store.NotFoundError as exc:
        raise HTTPException(status_code=404, detail="publication not found") from exc
