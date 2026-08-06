"""Durable Phase 2 source synchronization job."""

import os
from pathlib import Path

import httpx

from app.ingestion.adapters import DEFAULT_ADAPTERS
from app.ingestion.collector import HTTPSCollector
from app.ingestion.service import IngestionService
from app.ingestion.storage import FilesystemArtifactStore
from app.ingestion.store import (
    PostgresIngestionRepository,
    load_source,
    mark_sync_status,
)
from app.procrastinate_app import procrastinate_app


@procrastinate_app.task(name="sync_provider_source")
def sync_provider_source(workspace_id: str, source_id: str, idempotency_key: str) -> None:
    source = load_source(workspace_id, source_id)
    mark_sync_status(workspace_id, source_id, idempotency_key, "running")
    storage_root = Path(os.environ.get("ARTIFACT_STORAGE_ROOT", "/tmp/delta-code-artifacts"))
    artifact_store = FilesystemArtifactStore(
        storage_root, retention_days=source.retention_days
    )
    try:
        with httpx.Client(
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=False,
            headers={"User-Agent": "Delta-Code-Ingestion/1.0"},
        ) as client:
            collector = HTTPSCollector(client, artifact_store)
            service = IngestionService(
                collector,
                artifact_store,
                PostgresIngestionRepository(),
                DEFAULT_ADAPTERS,
            )
            result = service.sync(source, idempotency_key=idempotency_key)
    except Exception as exc:
        mark_sync_status(
            workspace_id,
            source_id,
            idempotency_key,
            "failed",
            error_code=getattr(exc, "code", "sync_failed"),
        )
        raise
    mark_sync_status(
        workspace_id,
        source_id,
        idempotency_key,
        "completed",
        result=result.model_dump(mode="json"),
    )
