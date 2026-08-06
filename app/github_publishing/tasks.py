"""Durable GitHub publication tasks."""

import os
from pathlib import Path

from app.ingestion.storage import FilesystemArtifactStore
from app.procrastinate_app import procrastinate_app

from .patch import load_publication_edits
from .publisher import GitHubInstallationCredentialBroker, GitHubPullRequestPublisher
from .store import (
    DatabasePublicationProgress,
    claim_publication,
    complete_publication,
    fail_publication,
)


@procrastinate_app.task(name="publish_migration_draft")
def publish_migration_draft(workspace_id: str, publication_id: str) -> None:
    try:
        context = claim_publication(workspace_id, publication_id)
        if context is None:
            return
        if os.environ.get("GITHUB_PUBLISHING_ENABLED", "").lower() != "true":
            raise PermissionError("github_publishing_disabled")
        artifact_store = FilesystemArtifactStore(
            Path(os.environ.get("ARTIFACT_STORAGE_ROOT", ".delta-code-artifacts"))
        )
        edits = load_publication_edits(
            artifact_store,
            context.artifact_object_ref,
            context.record.patch_sha256,
        )
        publisher = GitHubPullRequestPublisher(GitHubInstallationCredentialBroker())
        result = publisher.publish(context, edits, DatabasePublicationProgress(context))
        complete_publication(context, result)
    except Exception as exc:
        error_code = getattr(exc, "code", None) or type(exc).__name__.lower()
        fail_publication(workspace_id, publication_id, str(error_code))
        raise
