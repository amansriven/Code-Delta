"""Authenticated-scrape metrics and dependency readiness endpoints."""

import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status

from app.db import get_connection
from app.hardening.metrics import registry

router = APIRouter(tags=["operations"])


def _database_ready() -> bool:
    try:
        with get_connection() as connection:
            connection.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


@router.get("/ready", include_in_schema=False)
def ready(response: Response) -> dict:
    checks = {
        "database": _database_ready(),
        "artifact_storage_configured": bool(os.environ.get("ARTIFACT_STORAGE_ROOT")),
        "sandbox_execution_enabled": os.environ.get("SANDBOX_EXECUTION_ENABLED", "").lower()
        == "true",
        "github_publishing_enabled": os.environ.get("GITHUB_PUBLISHING_ENABLED", "").lower()
        == "true",
    }
    if not checks["database"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        state = "not_ready"
    else:
        state = "ready"
    return {"status": state, "checks": checks}


@router.get("/metrics", include_in_schema=False)
def metrics(
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    expected = os.environ.get("METRICS_BEARER_TOKEN", "")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not expected:
        raise HTTPException(status_code=503, detail="metrics scraping is not configured")
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid metrics credentials")
    return Response(
        registry.render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )
