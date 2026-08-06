"""Synchronize developer decisions to an existing Delta Code draft."""

from .publisher import GitHubInstallationCredentialBroker, GitHubPullRequestPublisher
from .store import (
    audit_pull_request_action,
    load_pull_request_action,
    migration_has_opened_pull_request,
)


def synchronize_developer_action(
    workspace_id: str,
    migration_id: str,
    action: str,
    *,
    actor: str,
    expected_version: int,
) -> None:
    if action not in {"approve", "decline"}:
        return
    if not migration_has_opened_pull_request(workspace_id, migration_id):
        return
    context = load_pull_request_action(workspace_id, migration_id, expected_version)
    GitHubPullRequestPublisher(GitHubInstallationCredentialBroker()).synchronize_action(
        repository_full_name=context.repository_full_name,
        installation_id=context.installation_id,
        pull_number=context.pull_number,
        pull_node_id=context.pull_node_id,
        expected_head_sha=context.head_sha,
        action=action,
    )
    audit_pull_request_action(workspace_id, migration_id, action, actor)
