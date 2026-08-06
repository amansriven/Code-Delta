"""Version 1 repository intelligence contracts."""

from datetime import datetime
from typing import Literal

from pydantic import Field, HttpUrl

from app.control_plane.models import ContractModel, ImpactEvidence


class RepositoryRef(ContractModel):
    id: str
    workspace_id: str
    full_name: str = Field(pattern=r"^[^/]+/[^/]+$")
    clone_url: HttpUrl
    default_branch: str = Field(min_length=1)
    installation_id: int = Field(gt=0)


class RepositoryWorkspace(ContractModel):
    repository_id: str
    root: str
    commit_sha: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    content_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    file_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    symlink_count: int = Field(ge=0)


class LanguageObservation(ContractModel):
    language: str
    file_count: int = Field(ge=1)
    detection_method: Literal["extension"] = "extension"


class ManifestObservation(ContractModel):
    path: str
    kind: Literal["pyproject", "requirements", "package_json", "package_lock"]
    parsed: bool
    warning: str | None = None


class DependencyObservation(ContractModel):
    id: str
    ecosystem: Literal["pypi", "npm", "unknown"]
    package: str = Field(min_length=1)
    declared_specifier: str | None = None
    resolved_version: str | None = None
    source_path: str
    detection_method: Literal["manifest", "lockfile", "import", "other"]


class InventoryCapability(ContractModel):
    analyzer_id: str
    analyzer_version: str
    supported: bool
    languages: list[str]
    limitations: list[str] = Field(default_factory=list)


class InventoryResult(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    inventory_version: Literal["1.0.0"] = "1.0.0"
    repository_id: str
    commit_sha: str
    workspace_digest: str
    inventory_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    languages: list[LanguageObservation]
    manifests: list[ManifestObservation]
    dependencies: list[DependencyObservation]
    capabilities: list[InventoryCapability]
    files_considered: int = Field(ge=0)
    files_excluded: int = Field(ge=0)
    symlinks_excluded: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


class RepositorySnapshot(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str
    repository_id: str
    commit_sha: str
    content_digest: str
    inventory_digest: str
    inventory_version: str
    analyzer_versions: list[str]
    created_at: datetime


class RepositoryAnalysisResult(ContractModel):
    snapshot: RepositorySnapshot
    inventory: InventoryResult
    impact: ImpactEvidence

