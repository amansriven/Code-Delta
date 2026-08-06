from collections.abc import Iterator
from importlib import import_module

import pytest
from fastapi.testclient import TestClient

from app.control_plane import store as control_plane_store
from app.main import app
from app.oauth import get_session


@pytest.fixture
def client(monkeypatch) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: {
        "github_user_id": 7,
        "github_login": "octocat",
        "repositories": [],
    }
    monkeypatch.setattr(
        control_plane_store,
        "ensure_workspace",
        lambda _session: "workspace-7",
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_publication_is_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("GITHUB_PUBLISHING_ENABLED", raising=False)

    response = client.post(
        "/migrations/migration-1/publish",
        headers={"Origin": "http://localhost:3000", "Idempotency-Key": "publish-123"},
        json={"expected_version": 4},
    )

    assert response.status_code == 503


def test_publication_queues_workspace_scoped_task(client, monkeypatch):
    router = import_module("app.github_publishing.router")
    monkeypatch.setenv("GITHUB_PUBLISHING_ENABLED", "true")
    captured = {}
    deferred = []

    def queue(workspace_id, migration_id, **kwargs):
        captured.update(workspace_id=workspace_id, migration_id=migration_id, **kwargs)
        return {
            "migration_id": migration_id,
            "attempt_id": "attempt-1",
            "publication_id": "publication-1",
            "status": "queued",
            "version": 5,
        }

    monkeypatch.setattr(router.store, "queue_publication", queue)
    monkeypatch.setattr(
        router.publish_migration_draft,
        "defer",
        lambda **kwargs: deferred.append(kwargs),
    )

    response = client.post(
        "/migrations/migration-1/publish",
        headers={"Origin": "http://localhost:3000", "Idempotency-Key": "publish-123"},
        json={"expected_version": 4},
    )

    assert response.status_code == 202
    assert captured["workspace_id"] == "workspace-7"
    assert captured["actor"] == "octocat"
    assert deferred == [
        {"workspace_id": "workspace-7", "publication_id": "publication-1"}
    ]


def test_publication_rejects_cross_site_mutation(client, monkeypatch):
    monkeypatch.setenv("GITHUB_PUBLISHING_ENABLED", "true")
    response = client.post(
        "/migrations/migration-1/publish",
        headers={"Origin": "https://attacker.example", "Idempotency-Key": "publish-123"},
        json={"expected_version": 4},
    )

    assert response.status_code == 403
