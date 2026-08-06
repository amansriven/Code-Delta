from types import SimpleNamespace

import pytest

from app.repository_intelligence import tasks
from app.repository_intelligence.models import RepositoryWorkspace


def test_enqueue_fans_out_only_durable_queued_jobs(monkeypatch):
    deferred = []
    monkeypatch.setattr(tasks, "queued_fanout_job_ids", lambda *_args: ["job-1", "job-2"])
    monkeypatch.setattr(
        tasks.analyze_repository_fanout,
        "defer",
        lambda **kwargs: deferred.append(kwargs),
    )

    tasks.enqueue_repository_analysis.func("workspace-1", ["change-1"])

    assert deferred == [
        {"workspace_id": "workspace-1", "job_id": "job-1"},
        {"workspace_id": "workspace-1", "job_id": "job-2"},
    ]


def test_analysis_uses_opaque_credential_handle_and_always_cleans_up(monkeypatch, tmp_path):
    repository = SimpleNamespace(id="repo-1", installation_id=17, default_branch="main")
    context = SimpleNamespace(repository=repository, change=object())
    repo_workspace = RepositoryWorkspace(
        repository_id="repo-1",
        root=str(tmp_path),
        commit_sha="a" * 40,
        content_digest="sha256:" + "b" * 64,
        file_count=0,
        size_bytes=0,
        symlink_count=0,
    )
    events = []

    class Provider:
        def __init__(self, _broker):
            pass

        def materialize(self, selected_repository, ref, credential_handle):
            events.append(("materialize", selected_repository.id, ref, credential_handle))
            return repo_workspace

        def cleanup(self, selected_workspace):
            events.append(("cleanup", selected_workspace.root))

    class Service:
        def analyze(self, *_args):
            return "result"

    monkeypatch.setattr(tasks, "GitRepositoryWorkspaceProvider", Provider)
    monkeypatch.setattr(tasks, "GitHubInstallationCredentialBroker", lambda: object())
    monkeypatch.setattr(tasks, "RepositoryIntelligenceService", Service)
    monkeypatch.setattr(tasks, "claim_fanout_job", lambda *_args: context)
    monkeypatch.setattr(
        tasks,
        "complete_fanout_job",
        lambda _context, result: events.append(("complete", result)),
    )

    tasks.analyze_repository_fanout.func("workspace-1", "job-1")

    assert events == [
        ("materialize", "repo-1", "main", "github-installation:17"),
        ("complete", "result"),
        ("cleanup", str(tmp_path)),
    ]


def test_analysis_failure_persists_only_safe_error_code(monkeypatch):
    failures = []
    context = SimpleNamespace(
        repository=SimpleNamespace(id="repo-1", installation_id=17, default_branch="main"),
        change=object(),
    )

    class Provider:
        def __init__(self, _broker):
            pass

        def materialize(self, *_args):
            raise RuntimeError("secret-token should never be persisted")

    monkeypatch.setattr(tasks, "GitRepositoryWorkspaceProvider", Provider)
    monkeypatch.setattr(tasks, "GitHubInstallationCredentialBroker", lambda: object())
    monkeypatch.setattr(tasks, "claim_fanout_job", lambda *_args: context)
    monkeypatch.setattr(
        tasks,
        "fail_fanout_job",
        lambda workspace_id, job_id, code: failures.append((workspace_id, job_id, code)),
    )

    with pytest.raises(RuntimeError, match="secret-token"):
        tasks.analyze_repository_fanout.func("workspace-1", "job-1")

    assert failures == [("workspace-1", "job-1", "runtimeerror")]
