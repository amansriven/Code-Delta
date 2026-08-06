from collections.abc import Iterator
from importlib import import_module

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.oauth import get_session
from app.repository_intelligence import store


@pytest.fixture
def client(monkeypatch) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: {
        "github_user_id": 7,
        "github_login": "octocat",
        "repositories": [],
    }
    router_module = import_module("app.repository_intelligence.router")
    monkeypatch.setattr(router_module, "ensure_workspace", lambda _session: "workspace-7")
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_snapshot_feed_is_workspace_and_repository_scoped(client, monkeypatch):
    calls = []

    def fake_list(workspace_id, repository_id, *, cursor, limit):
        calls.append((workspace_id, repository_id, cursor, limit))
        return ([{"id": "snapshot-1"}], "next")

    monkeypatch.setattr(store, "list_repository_snapshots", fake_list)

    response = client.get("/repositories/repo-1/snapshots?cursor=prior&limit=10")

    assert response.status_code == 200
    assert response.json() == {"items": [{"id": "snapshot-1"}], "next_cursor": "next"}
    assert calls == [("workspace-7", "repo-1", "prior", 10)]


def test_change_impact_feed_is_workspace_scoped(client, monkeypatch):
    monkeypatch.setattr(
        store,
        "list_change_impacts",
        lambda workspace_id, change_id, **_kwargs: (
            [{"assessment_id": f"{workspace_id}:{change_id}"}],
            None,
        ),
    )

    response = client.get("/changes/change-1/impacts")

    assert response.status_code == 200
    assert response.json()["items"] == [{"assessment_id": "workspace-7:change-1"}]


def test_missing_impact_is_not_leaked_across_workspaces(client, monkeypatch):
    from app.control_plane.store import NotFoundError

    monkeypatch.setattr(
        store,
        "get_impact",
        lambda *_args: (_ for _ in ()).throw(NotFoundError("missing")),
    )

    response = client.get("/impact-assessments/impact-1")

    assert response.status_code == 404
