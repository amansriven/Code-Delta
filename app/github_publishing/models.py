"""Phase 5 publisher contracts."""

from typing import Literal

from pydantic import Field

from app.control_plane.models import ContractModel, MigrationEvidence
from app.repository_intelligence.models import RepositoryRef


class PublicationEdit(ContractModel):
    path: str
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    content: str
    plan_step_ids: list[str] = Field(min_length=1)


class PublicationRecord(ContractModel):
    id: str
    migration_id: str
    last_attempt_id: str
    status: Literal["queued", "publishing", "completed", "failed"]
    branch: str
    base_sha: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    patch_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    tree_sha: str | None = None
    commit_sha: str | None = None
    remote_head_sha: str | None = None
    pull_number: int | None = Field(default=None, ge=1)
    pull_node_id: str | None = None
    pull_url: str | None = None
    check_run_id: int | None = Field(default=None, ge=1)


class PublicationContext(ContractModel):
    workspace_id: str
    repository: RepositoryRef
    evidence: MigrationEvidence
    artifact_object_ref: str
    record: PublicationRecord


class GitHubCredentials(ContractModel):
    token: str = Field(min_length=1, repr=False)
    permissions: dict[str, str]


class PublicationResult(ContractModel):
    tree_sha: str
    commit_sha: str
    branch: str
    pull_number: int = Field(ge=1)
    pull_node_id: str
    pull_url: str
    check_run_id: int = Field(ge=1)
