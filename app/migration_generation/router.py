"""Authenticated Phase 4 generation endpoint."""

from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.control_plane import store as control_plane_store
from app.control_plane.models import GenerateMigrationRequest
from app.control_plane.state import StateTransitionError, VersionConflictError
from app.oauth import FRONTEND_URL, get_session

from . import store
from .tasks import run_migration_generation

router = APIRouter(tags=["migration-generation"])


def _workspace(session: Annotated[dict, Depends(get_session)]) -> tuple[str, dict]:
    return control_plane_store.ensure_workspace(session), session


def _require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    trusted = urlparse(FRONTEND_URL)
    candidate = urlparse(origin) if origin else None
    if not candidate or (candidate.scheme, candidate.netloc) != (trusted.scheme, trusted.netloc):
        raise HTTPException(status_code=403, detail="untrusted mutation origin")


@router.post(
    "/migrations/{migration_id}/generate",
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_migration(
    migration_id: str,
    body: GenerateMigrationRequest,
    request: Request,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=200),
    ],
):
    _require_trusted_origin(request)
    workspace_id, session = context
    try:
        response = store.queue_attempt(
            workspace_id,
            migration_id,
            actor=session["github_login"],
            expected_version=body.expected_version,
            idempotency_key=idempotency_key,
        )
        run_migration_generation.defer(
            workspace_id=workspace_id,
            attempt_id=response["attempt_id"],
        )
        return response
    except control_plane_store.NotFoundError as exc:
        raise HTTPException(status_code=404, detail="migration not found") from exc
    except (VersionConflictError, StateTransitionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except control_plane_store.IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

