from types import SimpleNamespace

import pytest

from app.github_publishing import tasks


def test_publication_task_uses_exact_artifact_and_completes(monkeypatch):
    context = SimpleNamespace(
        artifact_object_ref="object-ref",
        record=SimpleNamespace(patch_sha256="a" * 64),
    )
    events = []
    monkeypatch.setenv("GITHUB_PUBLISHING_ENABLED", "true")
    monkeypatch.setattr(tasks, "claim_publication", lambda *_args: context)
    monkeypatch.setattr(tasks, "FilesystemArtifactStore", lambda *_args: "store")
    monkeypatch.setattr(
        tasks,
        "load_publication_edits",
        lambda store, object_ref, digest: events.append(
            ("load", store, object_ref, digest)
        )
        or ["edit"],
    )
    monkeypatch.setattr(tasks, "DatabasePublicationProgress", lambda value: value)

    class Publisher:
        def __init__(self, _broker):
            pass

        def publish(self, selected_context, edits, _progress):
            events.append(("publish", selected_context, edits))
            return "result"

    monkeypatch.setattr(tasks, "GitHubPullRequestPublisher", Publisher)
    monkeypatch.setattr(tasks, "GitHubInstallationCredentialBroker", lambda: object())
    monkeypatch.setattr(
        tasks,
        "complete_publication",
        lambda selected_context, result: events.append(("complete", selected_context, result)),
    )

    tasks.publish_migration_draft.func("workspace-1", "publication-1")

    assert events == [
        ("load", "store", "object-ref", "a" * 64),
        ("publish", context, ["edit"]),
        ("complete", context, "result"),
    ]


def test_partial_publication_failure_persists_only_safe_code(monkeypatch):
    failures = []
    monkeypatch.setenv("GITHUB_PUBLISHING_ENABLED", "true")
    monkeypatch.setattr(tasks, "claim_publication", lambda *_args: SimpleNamespace())
    monkeypatch.setattr(
        tasks,
        "FilesystemArtifactStore",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("secret-token")),
    )
    monkeypatch.setattr(
        tasks,
        "fail_publication",
        lambda workspace_id, publication_id, code: failures.append(
            (workspace_id, publication_id, code)
        ),
    )

    with pytest.raises(RuntimeError, match="secret-token"):
        tasks.publish_migration_draft.func("workspace-1", "publication-1")

    assert failures == [("workspace-1", "publication-1", "runtimeerror")]


def test_worker_gate_fails_claimed_publication_when_disabled(monkeypatch):
    failures = []
    monkeypatch.delenv("GITHUB_PUBLISHING_ENABLED", raising=False)
    monkeypatch.setattr(tasks, "claim_publication", lambda *_args: SimpleNamespace())
    monkeypatch.setattr(
        tasks,
        "fail_publication",
        lambda workspace_id, publication_id, code: failures.append(
            (workspace_id, publication_id, code)
        ),
    )

    with pytest.raises(PermissionError):
        tasks.publish_migration_draft.func("workspace-1", "publication-1")

    assert failures == [("workspace-1", "publication-1", "permissionerror")]
