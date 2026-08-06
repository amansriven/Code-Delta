"""Authenticated provider/source configuration and health API."""

from typing import Annotated
from urllib.parse import urlparse

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)

from app.control_plane.store import IdempotencyConflictError, NotFoundError, ensure_workspace
from app.ingestion import store
from app.ingestion.adapters import DEFAULT_ADAPTERS
from app.ingestion.models import CreateProviderRequest, CreateSourceRequest
from app.ingestion.security import SourcePolicyError, validate_source_url
from app.oauth import FRONTEND_URL, get_session

router = APIRouter(tags=["ingestion"])


def _workspace(session: Annotated[dict, Depends(get_session)]) -> tuple[str, dict]:
    return ensure_workspace(session), session


def _require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    trusted = urlparse(FRONTEND_URL)
    candidate = urlparse(origin) if origin else None
    if not candidate or (candidate.scheme, candidate.netloc) != (trusted.scheme, trusted.netloc):
        raise HTTPException(status_code=403, detail="untrusted mutation origin")


@router.post("/providers", status_code=status.HTTP_201_CREATED)
def create_provider(
    body: CreateProviderRequest,
    request: Request,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
):
    _require_trusted_origin(request)
    workspace_id, session = context
    try:
        return store.create_provider(
            workspace_id,
            body,
            actor=session["github_login"],
            idempotency_key=idempotency_key,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except store.ResourceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/providers/{provider_id}/sources", status_code=status.HTTP_201_CREATED)
def create_source(
    provider_id: str,
    body: CreateSourceRequest,
    request: Request,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
):
    _require_trusted_origin(request)
    adapter = DEFAULT_ADAPTERS.get(body.adapter_id)
    if adapter is None or body.source_type not in adapter.capabilities().source_types:
        raise HTTPException(status_code=422, detail="adapter does not support this source type")
    try:
        validate_source_url(str(body.canonical_url), body.official_domains)
    except SourcePolicyError as exc:
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    workspace_id, session = context
    try:
        return store.create_source(
            workspace_id,
            provider_id,
            body,
            actor=session["github_login"],
            idempotency_key=idempotency_key,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="provider not found") from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except store.ResourceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/providers/{provider_id}/sources")
def list_sources(
    provider_id: str,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
):
    try:
        items, next_cursor = store.list_sources(
            context[0], provider_id, cursor=cursor, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": items, "next_cursor": next_cursor}


@router.post(
    "/providers/{provider_id}/sources/{source_id}/sync",
    status_code=status.HTTP_202_ACCEPTED,
)
def request_source_sync(
    provider_id: str,
    source_id: str,
    request: Request,
    context: Annotated[tuple[str, dict], Depends(_workspace)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
):
    _require_trusted_origin(request)
    workspace_id, session = context
    try:
        source = store.load_source(workspace_id, source_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="source not found") from exc
    if source.provider.id != provider_id:
        raise HTTPException(status_code=404, detail="source not found")
    created, sync_status = store.queue_source_sync(
        workspace_id,
        source_id,
        actor=session["github_login"],
        idempotency_key=idempotency_key,
    )
    if created:
        try:
            _defer_source_sync(workspace_id, source_id, idempotency_key)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="source sync could not be queued") from exc
    return {
        "source_id": source_id,
        "status": sync_status,
        "idempotency_key": idempotency_key,
    }


def _defer_source_sync(workspace_id: str, source_id: str, idempotency_key: str) -> None:
    from app.ingestion.tasks import sync_provider_source

    try:
        sync_provider_source.defer(
            workspace_id=workspace_id,
            source_id=source_id,
            idempotency_key=idempotency_key,
        )
    except Exception:
        store.mark_sync_status(
            workspace_id,
            source_id,
            idempotency_key,
            "failed",
            error_code="queue_failed",
        )
        raise
