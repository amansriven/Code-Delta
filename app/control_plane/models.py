"""Version 1 control-plane contracts.

These models are deliberately provider- and language-neutral.  They are the
durable boundary between ingestion, repository analysis, orchestration, and
the HTTP API described by the Phase 0 contracts.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(StrEnum):
    deterministic = "deterministic"
    provider_stated = "provider_stated"
    model_inferred = "model_inferred"
    human_supplied = "human_supplied"


class ConfidenceBasis(StrEnum):
    deterministic = "deterministic"
    inferred = "inferred"
    mixed = "mixed"
    human_reviewed = "human_reviewed"


class Confidence(ContractModel):
    score: Annotated[float, Field(ge=0, le=1)]
    basis: ConfidenceBasis
    reasons: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class ProviderRef(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    product: str | None = None


class ComponentVersion(ContractModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class VersionScope(ContractModel):
    previous: str | None = None
    current: str | None = None
    affected_range: str | None = None
    fixed_range: str | None = None
    scheme: Literal["semver", "date", "api_version", "commit", "unversioned", "unknown"]


class SourceArtifactRef(ContractModel):
    id: str = Field(min_length=1)
    source_type: Literal[
        "openapi",
        "changelog",
        "migration_guide",
        "sdk_release",
        "package_registry",
        "documentation",
        "manual_official_submission",
        "other",
    ]
    canonical_url: HttpUrl
    captured_at: datetime
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    media_type: str | None = None
    authoritative: Literal[True]


class ChangeTarget(ContractModel):
    kind: Literal[
        "endpoint", "sdk_package", "symbol", "type", "field", "configuration",
        "authentication", "behavior"
    ]
    name: str = Field(min_length=1)
    operation: str | None = None
    package: str | None = None
    ecosystem: str | None = None
    language: str | None = None
    version_scope: VersionScope | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Guidance(ContractModel):
    summary: str = Field(min_length=1, max_length=4000)
    provenance: Provenance
    source_artifact_ids: list[str] = Field(min_length=1)


class Claim(Guidance):
    id: str = Field(min_length=1)
    locator: str | None = None


class NormalizedChange(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str = Field(min_length=1)
    dedupe_key: str = Field(min_length=1)
    supersedes: str | None = None
    provider: ProviderRef
    status: Literal[
        "detected", "normalizing", "needs_review", "ready", "invalid", "withdrawn",
        "superseded"
    ]
    detected_at: datetime
    published_at: datetime | None = None
    effective_at: datetime | None = None
    deprecation_at: datetime | None = None
    change_type: Literal[
        "endpoint_added", "endpoint_removed", "endpoint_changed", "request_field_added",
        "request_field_removed", "request_field_required", "request_field_optional",
        "request_field_type_changed", "response_field_added", "response_field_removed",
        "response_field_type_changed", "authentication_changed", "behavior_changed",
        "sdk_symbol_added", "sdk_symbol_removed", "sdk_symbol_changed", "sdk_release",
        "deprecation", "feature", "security", "unknown"
    ]
    severity: Literal["informational", "low", "medium", "high", "critical", "unknown"]
    breaking: bool | None = None
    summary: str = Field(min_length=1, max_length=2000)
    before: Any = None
    after: Any = None
    version_scope: VersionScope | None = None
    source_artifacts: list[SourceArtifactRef] = Field(min_length=1)
    targets: list[ChangeTarget] = Field(min_length=1)
    migration_guidance: list[Guidance] = Field(default_factory=list)
    claims: list[Claim] = Field(min_length=1)
    confidence: Confidence
    normalizer: ComponentVersion | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def claims_reference_captured_artifacts(self) -> "NormalizedChange":
        artifact_ids = {artifact.id for artifact in self.source_artifacts}
        references = [
            source_id
            for item in [*self.claims, *self.migration_guidance]
            for source_id in item.source_artifact_ids
        ]
        unknown = sorted(set(references) - artifact_ids)
        if unknown:
            raise ValueError(f"claims reference unknown source artifacts: {', '.join(unknown)}")
        return self


class EvidenceRepository(ContractModel):
    id: str
    full_name: str = Field(pattern=r"^[^/]+/[^/]+$")
    base_branch: str = Field(min_length=1)
    base_commit_sha: str = Field(pattern=r"^[a-fA-F0-9]{7,64}$")
    snapshot_digest: str = Field(min_length=1)


class DependencyMatch(ContractModel):
    ecosystem: str
    package: str
    resolved_version: str | None = None
    source_path: str | None = None
    detection_method: Literal[
        "manifest", "lockfile", "generated_client", "import", "configuration", "endpoint", "other"
    ]
    evidence: str = Field(min_length=1)


class CallSite(ContractModel):
    id: str
    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    language: str | None = None
    symbol: str | None = None
    target: str | None = None
    detection_method: Literal[
        "lockfile", "ast", "type_index", "symbol_index", "generated_code", "configuration",
        "text_heuristic", "model_inference"
    ]
    reason: str = Field(min_length=1)
    confidence: Confidence

    @model_validator(mode="after")
    def line_range_is_ordered(self) -> "CallSite":
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class Coverage(ContractModel):
    supported: bool
    languages: list[str] = Field(default_factory=list)
    files_considered: int = Field(ge=0)
    files_excluded: int = Field(ge=0)
    parse_failures: int = Field(ge=0)
    limitations: list[str]


class ImpactEvidence(ContractModel):
    assessment_id: str
    conclusion: Literal["affected", "unaffected", "uncertain", "unsupported", "failed"]
    summary: str = Field(min_length=1)
    dependency_matches: list[DependencyMatch] = Field(default_factory=list)
    call_sites: list[CallSite]
    coverage: Coverage
    confidence: Confidence

    @model_validator(mode="after")
    def unaffected_requires_supported_coverage(self) -> "ImpactEvidence":
        if self.conclusion == "unaffected" and not self.coverage.supported:
            raise ValueError("unaffected evidence requires supported coverage")
        return self


class PlanStep(ContractModel):
    id: str
    description: str = Field(min_length=1)
    call_site_ids: list[str]
    expected_paths: list[str]


class MigrationPlan(ContractModel):
    summary: str = Field(min_length=1)
    steps: list[PlanStep] = Field(min_length=1)
    verification_strategy: list[str]
    assumptions: list[str]
    unresolved: list[str]


class FileChange(ContractModel):
    path: str = Field(min_length=1)
    change_type: Literal["added", "modified", "deleted", "renamed"]
    previous_path: str | None = None
    plan_step_ids: list[str] = Field(min_length=1)


class PatchEvidence(ContractModel):
    artifact_id: str
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    summary: str = Field(min_length=1)
    files: list[FileChange] = Field(min_length=1)


class TestChange(ContractModel):
    path: str
    action: Literal["added", "modified", "deleted"]
    purpose: str = Field(min_length=1)
    provenance: Literal["generated", "existing_modified", "deterministic_fixture", "human_supplied"]


class VerificationCheck(ContractModel):
    id: str
    kind: Literal[
        "dependency_install", "format", "lint", "type_check", "build", "unit_test",
        "generated_test", "behavioral_verification", "security_policy", "other"
    ]
    status: Literal[
        "passed", "failed", "skipped", "timed_out", "blocked", "infrastructure_error"
    ]
    deterministic: Literal[True]
    command: str | None = None
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    executor: ComponentVersion
    summary: str
    display_log: str | None = Field(default=None, max_length=20000)
    log_artifact_id: str | None = None


class BehavioralEvidence(ContractModel):
    id: str
    check_id: str
    summary: str
    observed: Literal[True]
    before: Any = None
    after: Any = None
    artifact_ids: list[str] = Field(default_factory=list)


class ReviewFinding(ContractModel):
    severity: Literal["info", "low", "medium", "high", "critical"]
    path: str | None = None
    line: int | None = Field(default=None, ge=1)
    summary: str
    resolved: bool


class AttemptReview(ContractModel):
    summary: str
    findings: list[ReviewFinding]
    provenance: Literal["model_inferred"]
    model: ComponentVersion


class Recommendation(ContractModel):
    action: Literal["approve", "revise", "snooze", "decline"]
    rationale: str = Field(min_length=1)
    confidence: Confidence
    unresolved: list[str]


class PullRequestEvidence(ContractModel):
    provider: Literal["github"]
    repository: str
    number: int = Field(ge=1)
    url: HttpUrl
    draft: bool
    branch: str
    head_sha: str = Field(pattern=r"^[a-fA-F0-9]{7,64}$")
    status: Literal["opening", "open", "ready", "closed", "merged", "failed"]


class AttemptCost(ContractModel):
    currency: Literal["USD"] | None = None
    model_input_tokens: int | None = Field(default=None, ge=0)
    model_output_tokens: int | None = Field(default=None, ge=0)
    model_cost: float | None = Field(default=None, ge=0)
    sandbox_seconds: float | None = Field(default=None, ge=0)


class MigrationEvidence(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    migration_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    previous_attempt_id: str | None = None
    change_event_id: str = Field(min_length=1)
    repository: EvidenceRepository
    impact: ImpactEvidence
    plan: MigrationPlan
    patch: PatchEvidence
    tests: list[TestChange]
    verification_checks: list[VerificationCheck] = Field(min_length=1)
    behavioral_evidence: list[BehavioralEvidence] = Field(default_factory=list)
    review: AttemptReview
    recommendation: Recommendation
    pull_request: PullRequestEvidence | None = None
    tool_versions: list[ComponentVersion] = Field(default_factory=list)
    cost: AttemptCost | None = None
    created_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def evidence_references_are_consistent(self) -> "MigrationEvidence":
        if self.completed_at < self.created_at:
            raise ValueError("completed_at must be greater than or equal to created_at")
        check_ids = {check.id for check in self.verification_checks}
        unknown_checks = {item.check_id for item in self.behavioral_evidence} - check_ids
        if unknown_checks:
            raise ValueError("behavioral evidence references an unknown verification check")
        return self


class RepositorySummary(ContractModel):
    id: str
    full_name: str
    default_branch: str
    enabled: bool = True
    languages: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    updated_at: datetime


class ProviderSummary(ContractModel):
    id: str
    name: str
    product: str | None = None
    status: Literal["active", "paused", "degraded", "disconnected"] = "active"
    source_count: int = 0
    last_synced_at: datetime | None = None
    updated_at: datetime


class ChangeSummary(ContractModel):
    id: str
    provider: ProviderRef
    status: str
    change_type: str
    severity: str
    breaking: bool | None = None
    summary: str
    effective_at: datetime | None = None
    confidence: Confidence
    version: int
    created_at: datetime
    updated_at: datetime


class AttemptSummary(ContractModel):
    id: str
    number: int
    status: str
    recommendation: str | None = None
    previous_attempt_id: str | None = None
    evidence: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class MigrationSummary(ContractModel):
    id: str
    change_event_id: str
    repository_id: str
    repository_full_name: str
    provider_name: str
    change_summary: str
    risk: str
    status: str
    decision_state: str | None = None
    current_attempt_id: str | None = None
    pull_request_url: str | None = None
    snoozed_until: datetime | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class MigrationDetail(MigrationSummary):
    attempts: list[AttemptSummary] = Field(default_factory=list)


class DeveloperActionRequest(ContractModel):
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=4000)
    instructions: str | None = Field(default=None, max_length=8000)
    snooze_until: datetime | None = None


class GenerateMigrationRequest(ContractModel):
    expected_version: int = Field(ge=1)


class AuditEvent(ContractModel):
    id: str
    actor: str
    action: str
    entity_type: str
    entity_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class OrchestrationJob(ContractModel):
    """Serializable envelope carried by every durable control-plane job."""

    workspace_id: str = Field(min_length=1)
    entity_type: Literal["change_event", "impact_assessment", "migration", "attempt"]
    entity_id: str = Field(min_length=1)
    expected_state: str = Field(min_length=1)
    expected_version: int = Field(ge=1)
    requested_state: str = Field(min_length=1)
    contract_version: Literal["1.0"] = "1.0"
    implementation_version: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=8, max_length=200)
    attempt_number: int | None = Field(default=None, ge=1)
    trace_id: str = Field(min_length=1)
    causation_id: str = Field(min_length=1)


class Page(ContractModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = None
