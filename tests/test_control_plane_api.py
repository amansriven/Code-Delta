from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.control_plane import store
from app.main import app
from app.oauth import get_session


@pytest.fixture
def client(monkeypatch) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: {
        "github_user_id": 7,
        "github_login": "octocat",
        "repositories": [],
    }
    monkeypatch.setattr(store, "ensure_workspace", lambda _session: "workspace-7")
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_change_feed_is_workspace_scoped_and_cursor_paginated(client, monkeypatch):
    calls = []

    def fake_list(workspace_id, table, columns, *, cursor, limit):
        calls.append((workspace_id, table, columns, cursor, limit))
        return ([{"id": "change-1", "data": {"id": "change-1"}, "created_at": None}], "next")

    monkeypatch.setattr(store, "list_records", fake_list)

    response = client.get("/changes?cursor=previous&limit=10")

    assert response.status_code == 200
    assert response.json() == {"items": [{"id": "change-1"}], "next_cursor": "next"}
    assert calls[0][0:2] == ("workspace-7", "change_events")
    assert calls[0][3:] == ("previous", 10)


def test_developer_action_requires_trusted_origin(client, monkeypatch):
    monkeypatch.setattr(store, "apply_developer_action", lambda *_args, **_kwargs: {})

    response = client.post(
        "/migrations/migration-1/approve",
        headers={"Idempotency-Key": "approve-123", "Origin": "https://attacker.example"},
        json={"expected_version": 2},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "untrusted mutation origin"


def test_revision_passes_optimistic_version_and_idempotency_key(client, monkeypatch):
    captured = {}

    def fake_action(workspace_id, migration_id, action, **kwargs):
        captured.update(
            workspace_id=workspace_id, migration_id=migration_id, action=action, **kwargs
        )
        return {"id": migration_id, "status": "needs_revision", "version": 4}

    monkeypatch.setattr(store, "apply_developer_action", fake_action)

    response = client.post(
        "/migrations/migration-1/revise",
        headers={"Idempotency-Key": "revision-123", "Origin": "http://localhost:3000"},
        json={
            "expected_version": 3,
            "reason": "The repository uses an internal wrapper.",
            "instructions": "Update the wrapper rather than each caller.",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "needs_revision"
    assert captured["workspace_id"] == "workspace-7"
    assert captured["actor"] == "octocat"
    assert captured["expected_version"] == 3
    assert captured["idempotency_key"] == "revision-123"


def test_stale_developer_action_returns_conflict(client, monkeypatch):
    def stale(*_args, **_kwargs):
        from app.control_plane.state import VersionConflictError

        raise VersionConflictError("expected version 2, found 3")

    monkeypatch.setattr(store, "apply_developer_action", stale)

    response = client.post(
        "/migrations/migration-1/approve",
        headers={"Idempotency-Key": "approve-123", "Origin": "http://localhost:3000"},
        json={"expected_version": 2},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "expected version 2, found 3"
