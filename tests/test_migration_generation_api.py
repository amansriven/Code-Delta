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


def test_generation_is_workspace_scoped_idempotent_and_deferred(client, monkeypatch):
    router = import_module("app.migration_generation.router")
    captured = {}
    deferred = []

    def queue(workspace_id, migration_id, **kwargs):
        captured.update(workspace_id=workspace_id, migration_id=migration_id, **kwargs)
        return {
            "migration_id": migration_id,
            "attempt_id": "attempt-1",
            "status": "planning",
            "version": 4,
        }

    monkeypatch.setattr(router.store, "queue_attempt", queue)
    monkeypatch.setattr(
        router.run_migration_generation,
        "defer",
        lambda **kwargs: deferred.append(kwargs),
    )

    response = client.post(
        "/migrations/migration-1/generate",
        headers={"Idempotency-Key": "generate-123", "Origin": "http://localhost:3000"},
        json={"expected_version": 3},
    )

    assert response.status_code == 202
    assert response.json()["attempt_id"] == "attempt-1"
    assert captured == {
        "workspace_id": "workspace-7",
        "migration_id": "migration-1",
        "actor": "octocat",
        "expected_version": 3,
        "idempotency_key": "generate-123",
    }
    assert deferred == [{"workspace_id": "workspace-7", "attempt_id": "attempt-1"}]


def test_generation_rejects_untrusted_browser_origin(client, monkeypatch):
    router = import_module("app.migration_generation.router")
    monkeypatch.setattr(router.store, "queue_attempt", lambda *_args, **_kwargs: {})

    response = client.post(
        "/migrations/migration-1/generate",
        headers={"Idempotency-Key": "generate-123", "Origin": "https://attacker.example"},
        json={"expected_version": 3},
    )

    assert response.status_code == 403


def test_generation_returns_optimistic_version_conflict(client, monkeypatch):
    router = import_module("app.migration_generation.router")

    def stale(*_args, **_kwargs):
        from app.control_plane.state import VersionConflictError

        raise VersionConflictError("expected version 2, found 3")

    monkeypatch.setattr(router.store, "queue_attempt", stale)

    response = client.post(
        "/migrations/migration-1/generate",
        headers={"Idempotency-Key": "generate-123", "Origin": "http://localhost:3000"},
        json={"expected_version": 2},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "expected version 2, found 3"

