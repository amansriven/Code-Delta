"""Durable Phase 3 repository analysis jobs."""

from app.procrastinate_app import procrastinate_app
from app.repository_intelligence.service import RepositoryIntelligenceService
from app.repository_intelligence.store import (
    claim_fanout_job,
    complete_fanout_job,
    fail_fanout_job,
    queued_fanout_job_ids,
)
from app.repository_intelligence.workspace import (
    GitHubInstallationCredentialBroker,
    GitRepositoryWorkspaceProvider,
)


@procrastinate_app.task(name="enqueue_repository_analysis")
def enqueue_repository_analysis(workspace_id: str, change_event_ids: list[str]) -> None:
    for job_id in queued_fanout_job_ids(workspace_id, change_event_ids):
        analyze_repository_fanout.defer(workspace_id=workspace_id, job_id=job_id)


@procrastinate_app.task(name="analyze_repository_fanout")
def analyze_repository_fanout(workspace_id: str, job_id: str) -> None:
    workspace = None
    provider = GitRepositoryWorkspaceProvider(GitHubInstallationCredentialBroker())
    try:
        context = claim_fanout_job(workspace_id, job_id)
        if context is None:
            return
        credential_handle = f"github-installation:{context.repository.installation_id}"
        workspace = provider.materialize(
            context.repository,
            context.repository.default_branch,
            credential_handle,
        )
        result = RepositoryIntelligenceService().analyze(
            context.repository, workspace, context.change
        )
        complete_fanout_job(context, result)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or type(exc).__name__.lower()
        fail_fanout_job(workspace_id, job_id, str(error_code))
        raise
    finally:
        if workspace is not None:
            provider.cleanup(workspace)
