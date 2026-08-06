from collections.abc import Iterator
from importlib import import_module

import pytest
from fastapi.testclient import TestClient

from app.ingestion import store
from app.main import app
from app.oauth import get_session


@pytest.fixture
def client(monkeypatch) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: {
        "github_user_id": 7,
        "github_login": "octocat",
        "repositories": [],
    }
    router_module = import_module("app.ingestion.router")

    monkeypatch.setattr(router_module, "ensure_workspace", lambda _session: "workspace-7")
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_provider_creation_requires_trusted_origin(client, monkeypatch):
    monkeypatch.setattr(store, "create_provider", lambda *_args, **_kwargs: {})

    response = client.post(
        "/providers",
        headers={"Origin": "https://attacker.test", "Idempotency-Key": "provider-123"},
        json={"id": "example", "name": "Example"},
    )

    assert response.status_code == 403


def test_provider_creation_is_workspace_scoped_and_audited_by_store(client, monkeypatch):
    captured = {}

    def create(workspace_id, body, **kwargs):
        captured.update(workspace_id=workspace_id, body=body, **kwargs)
        return {"id": body.id, "name": body.name, "status": "disconnected"}

    monkeypatch.setattr(store, "create_provider", create)

    response = client.post(
        "/providers",
        headers={"Origin": "http://localhost:3000", "Idempotency-Key": "provider-123"},
        json={"id": "example", "name": "Example"},
    )

    assert response.status_code == 201
    assert captured["workspace_id"] == "workspace-7"
    assert captured["actor"] == "octocat"
    assert captured["idempotency_key"] == "provider-123"


def test_source_registration_validates_adapter_and_network_policy(client, monkeypatch):
    router_module = import_module("app.ingestion.router")

    monkeypatch.setattr(router_module, "validate_source_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        store,
        "create_source",
        lambda workspace_id, provider_id, body, **_kwargs: {
            "id": body.id,
            "provider_id": provider_id,
            "workspace_id": workspace_id,
        },
    )

    response = client.post(
        "/providers/example/sources",
        headers={"Origin": "http://localhost:3000", "Idempotency-Key": "source-12345"},
        json={
            "id": "openapi",
            "source_type": "openapi",
            "canonical_url": "https://api.example.com/openapi.json",
            "official_domains": ["example.com"],
            "adapter_id": "openapi.diff",
        },
    )

    assert response.status_code == 201
    assert response.json()["workspace_id"] == "workspace-7"


def test_source_health_feed_is_cursor_paginated(client, monkeypatch):
    calls = []

    def list_page(workspace_id, provider_id, *, cursor, limit):
        calls.append((workspace_id, provider_id, cursor, limit))
        return ([{"id": "openapi", "status": "healthy"}], "next-page")

    monkeypatch.setattr(store, "list_sources", list_page)

    response = client.get("/providers/example/sources?cursor=previous&limit=10")

    assert response.status_code == 200
    assert response.json()["next_cursor"] == "next-page"
    assert calls == [("workspace-7", "example", "previous", 10)]


def test_sync_request_is_queued_without_fetching_in_request_handler(client, monkeypatch):
    router_module = import_module("app.ingestion.router")

    source = type("Source", (), {"provider": type("Provider", (), {"id": "example"})()})()
    queued = []
    monkeypatch.setattr(store, "load_source", lambda *_args: source)
    monkeypatch.setattr(
        store,
        "queue_source_sync",
        lambda *_args, **_kwargs: (True, "queued"),
    )
    monkeypatch.setattr(
        router_module,
        "_defer_source_sync",
        lambda workspace_id, source_id, key: queued.append((workspace_id, source_id, key)),
    )

    response = client.post(
        "/providers/example/sources/openapi/sync",
        headers={"Origin": "http://localhost:3000", "Idempotency-Key": "sync-12345"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert queued == [("workspace-7", "openapi", "sync-12345")]


def test_repeated_sync_key_reuses_existing_request_without_second_job(client, monkeypatch):
    source = type("Source", (), {"provider": type("Provider", (), {"id": "example"})()})()
    queued = []
    monkeypatch.setattr(store, "load_source", lambda *_args: source)
    monkeypatch.setattr(
        store,
        "queue_source_sync",
        lambda *_args, **_kwargs: (False, "running"),
    )
    router_module = import_module("app.ingestion.router")
    monkeypatch.setattr(router_module, "_defer_source_sync", lambda *_args: queued.append(True))

    response = client.post(
        "/providers/example/sources/openapi/sync",
        headers={"Origin": "http://localhost:3000", "Idempotency-Key": "sync-12345"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert queued == []


def test_queue_failure_becomes_visible_service_unavailable(client, monkeypatch):
    router_module = import_module("app.ingestion.router")
    source = type("Source", (), {"provider": type("Provider", (), {"id": "example"})()})()
    monkeypatch.setattr(store, "load_source", lambda *_args: source)
    monkeypatch.setattr(
        store,
        "queue_source_sync",
        lambda *_args, **_kwargs: (True, "queued"),
    )
    monkeypatch.setattr(
        router_module,
        "_defer_source_sync",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("queue unavailable")),
    )

    response = client.post(
        "/providers/example/sources/openapi/sync",
        headers={"Origin": "http://localhost:3000", "Idempotency-Key": "sync-12345"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "source sync could not be queued"
