"""Version 1 contracts for source collection and artifact capture."""

from datetime import datetime
from typing import Literal

from pydantic import Field, HttpUrl

from app.control_plane.models import ContractModel, ProviderRef


class CreateProviderRequest(ContractModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=200)
    product: str | None = Field(default=None, max_length=200)


class CreateSourceRequest(ContractModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    source_type: Literal[
        "openapi", "structured_release", "changelog", "migration_guide", "sdk_release"
    ]
    canonical_url: HttpUrl
    official_domains: list[str] = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    max_artifact_bytes: int = Field(default=5_000_000, ge=1, le=25_000_000)
    retention_days: int = Field(default=90, ge=1, le=3650)


class ProviderSource(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    provider: ProviderRef
    source_type: Literal[
        "openapi", "structured_release", "changelog", "migration_guide", "sdk_release"
    ]
    canonical_url: HttpUrl
    official_domains: list[str] = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    enabled: bool = True
    max_artifact_bytes: int = Field(default=5_000_000, ge=1, le=25_000_000)
    retention_days: int = Field(default=90, ge=1, le=3650)


class ArtifactDescriptor(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    source_id: str
    canonical_url: HttpUrl
    official_domains: list[str] = Field(min_length=1)
    max_artifact_bytes: int = Field(ge=1)
    accepted_media_types: list[str] = Field(min_length=1)
    etag: str | None = None
    last_modified: str | None = None


class CapturedArtifact(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str
    source_id: str
    canonical_url: HttpUrl
    retrieved_url: HttpUrl
    captured_at: datetime
    retrieval_status: Literal["captured", "not_modified"]
    media_type: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    object_ref: str = Field(min_length=1)
    authoritative: Literal[True] = True
    authority_basis: Literal["configured_official_domain"] = "configured_official_domain"
    collector_id: str
    collector_version: str
    etag: str | None = None
    last_modified: str | None = None
    redirect_count: int = Field(default=0, ge=0)


class SourceHealth(ContractModel):
    source_id: str
    status: Literal["healthy", "degraded", "failing", "disabled", "never_synced"]
    consecutive_failures: int = Field(ge=0)
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_code: str | None = None
    current_artifact_id: str | None = None


class IngestionResult(ContractModel):
    source_id: str
    artifact_id: str | None = None
    artifact_created: bool = False
    unchanged: bool = False
    change_event_ids: list[str] = Field(default_factory=list)
    fanout_count: int = Field(default=0, ge=0)
