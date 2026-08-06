"""Orchestration for immutable repository inventory and static impact analysis."""

import uuid
from datetime import UTC, datetime

from app.control_plane.models import NormalizedChange
from app.repository_intelligence.analyzer import PythonAstImpactAnalyzer
from app.repository_intelligence.inventory import RepositoryInventoryBuilder
from app.repository_intelligence.models import (
    RepositoryAnalysisResult,
    RepositoryRef,
    RepositorySnapshot,
    RepositoryWorkspace,
)


class RepositoryIntelligenceService:
    def __init__(
        self,
        inventory_builder: RepositoryInventoryBuilder | None = None,
        analyzer: PythonAstImpactAnalyzer | None = None,
    ) -> None:
        self.inventory_builder = inventory_builder or RepositoryInventoryBuilder()
        self.analyzer = analyzer or PythonAstImpactAnalyzer()

    def analyze(
        self,
        repository: RepositoryRef,
        workspace: RepositoryWorkspace,
        change: NormalizedChange,
        *,
        now: datetime | None = None,
    ) -> RepositoryAnalysisResult:
        inventory = self.inventory_builder.build(workspace)
        impact = self.analyzer.analyze(repository, workspace, inventory, change)
        snapshot_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"repository-snapshot:{repository.id}:{workspace.content_digest}:"
                f"{inventory.inventory_digest}",
            )
        )
        snapshot = RepositorySnapshot(
            id=snapshot_id,
            repository_id=repository.id,
            source_ref=repository.default_branch,
            commit_sha=workspace.commit_sha,
            content_digest=workspace.content_digest,
            inventory_digest=inventory.inventory_digest,
            inventory_version=inventory.inventory_version,
            analyzer_versions=[f"{self.analyzer.analyzer_id}:{self.analyzer.analyzer_version}"],
            created_at=now or datetime.now(UTC),
        )
        return RepositoryAnalysisResult(snapshot=snapshot, inventory=inventory, impact=impact)
