from datetime import UTC, datetime
from pathlib import Path

from app.control_plane.models import NormalizedChange
from app.repository_intelligence.analyzer import PythonAstImpactAnalyzer
from app.repository_intelligence.inventory import RepositoryInventoryBuilder
from app.repository_intelligence.models import RepositoryRef, RepositoryWorkspace
from app.repository_intelligence.service import RepositoryIntelligenceService
from app.repository_intelligence.workspace import workspace_fingerprint


def repository() -> RepositoryRef:
    return RepositoryRef(
        id="repo-1",
        workspace_id="workspace-1",
        full_name="acme/example",
        clone_url="https://github.com/acme/example.git",
        default_branch="main",
        installation_id=7,
    )


def workspace(root: Path) -> RepositoryWorkspace:
    digest, files, size, symlinks = workspace_fingerprint(root)
    return RepositoryWorkspace(
        repository_id="repo-1",
        root=str(root),
        commit_sha="a" * 40,
        content_digest=digest,
        file_count=files,
        size_bytes=size,
        symlink_count=symlinks,
    )


def change(*targets: dict) -> NormalizedChange:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    return NormalizedChange(
        id="change-1",
        dedupe_key="provider:change-1",
        provider={"id": "provider", "name": "Provider"},
        status="ready",
        detected_at=now,
        change_type="sdk_symbol_removed",
        severity="high",
        breaking=True,
        summary="A provider surface changed.",
        source_artifacts=[
            {
                "id": "artifact-1",
                "source_type": "sdk_release",
                "canonical_url": "https://provider.example/releases/1",
                "captured_at": now,
                "sha256": "a" * 64,
                "authoritative": True,
            }
        ],
        targets=list(targets),
        claims=[
            {
                "id": "claim-1",
                "summary": "The surface changed.",
                "provenance": "provider_stated",
                "source_artifact_ids": ["artifact-1"],
            }
        ],
        confidence={"score": 1, "basis": "deterministic"},
    )


def analyze(root: Path, provider_change: NormalizedChange):
    repo_workspace = workspace(root)
    inventory = RepositoryInventoryBuilder().build(repo_workspace)
    return PythonAstImpactAnalyzer().analyze(
        repository(), repo_workspace, inventory, provider_change
    )


def test_ast_analyzer_finds_aliased_symbol_endpoint_and_field(tmp_path: Path):
    (tmp_path / "client.py").write_text(
        "from example_sdk import Client as C\n"
        "client = C()\n"
        "client.send('/v1/legacy', old_field='value')\n"
    )
    provider_change = change(
        {"kind": "symbol", "name": "Client.send"},
        {"kind": "endpoint", "name": "/v1/legacy", "operation": "POST"},
        {"kind": "field", "name": "old_field"},
    )

    result = analyze(tmp_path, provider_change)

    assert result.conclusion == "affected"
    assert result.coverage.supported is True
    assert {item.target for item in result.call_sites} == {
        "Client.send",
        "/v1/legacy",
        "old_field",
    }
    assert all(item.detection_method == "ast" for item in result.call_sites)


def test_sdk_package_manifest_match_is_deterministic_affected(tmp_path: Path):
    (tmp_path / "app.py").write_text("value = 1\n")
    (tmp_path / "requirements.txt").write_text("example-sdk==2.0.0\n")

    result = analyze(
        tmp_path,
        change({"kind": "sdk_package", "name": "example-sdk", "ecosystem": "pypi"}),
    )

    assert result.conclusion == "affected"
    assert result.dependency_matches[0].package == "example-sdk"
    assert result.dependency_matches[0].resolved_version == "2.0.0"


def test_resolved_dependency_outside_affected_range_does_not_match(tmp_path: Path):
    (tmp_path / "app.py").write_text("value = 1\n")
    (tmp_path / "requirements.txt").write_text("example-sdk==1.5.0\n")

    result = analyze(
        tmp_path,
        change(
            {
                "kind": "sdk_package",
                "name": "example-sdk",
                "ecosystem": "pypi",
                "version_scope": {"affected_range": ">=2,<3", "scheme": "semver"},
            }
        ),
    )

    assert result.conclusion == "unaffected"
    assert result.dependency_matches == []


def test_negative_result_requires_complete_supported_coverage(tmp_path: Path):
    (tmp_path / "app.py").write_text("print('safe')\n")

    result = analyze(tmp_path, change({"kind": "symbol", "name": "Client.send"}))

    assert result.conclusion == "unaffected"
    assert result.coverage.supported is True
    assert result.call_sites == []


def test_parse_failure_and_unsupported_language_are_uncertain(tmp_path: Path):
    (tmp_path / "broken.py").write_text("def broken(:\n")
    (tmp_path / "client.ts").write_text("client.send()\n")

    result = analyze(tmp_path, change({"kind": "symbol", "name": "Client.send"}))

    assert result.conclusion == "uncertain"
    assert result.coverage.supported is False
    assert result.coverage.parse_failures == 1
    assert "TypeScript" in result.coverage.languages


def test_inventory_warning_prevents_false_unaffected_result(tmp_path: Path):
    (tmp_path / "app.py").write_text("print('safe')\n")
    (tmp_path / "pyproject.toml").write_text("not valid toml = [\n")

    result = analyze(tmp_path, change({"kind": "symbol", "name": "Client.send"}))

    assert result.conclusion == "uncertain"
    assert result.coverage.supported is False
    assert any("inventory reported" in item.lower() for item in result.coverage.limitations)


def test_excluded_symlink_prevents_false_unaffected_result(tmp_path: Path):
    (tmp_path / "app.py").write_text("print('safe')\n")
    (tmp_path / "linked.py").symlink_to(tmp_path / "app.py")

    result = analyze(tmp_path, change({"kind": "symbol", "name": "Client.send"}))

    assert result.conclusion == "uncertain"
    assert result.coverage.files_excluded == 1


def test_repository_without_python_is_explicitly_unsupported(tmp_path: Path):
    (tmp_path / "client.ts").write_text("client.send()\n")

    result = analyze(tmp_path, change({"kind": "symbol", "name": "Client.send"}))

    assert result.conclusion == "unsupported"
    assert result.coverage.supported is False


def test_service_snapshot_identity_is_stable_for_same_immutable_input(tmp_path: Path):
    (tmp_path / "app.py").write_text("value = 1\n")
    repo_workspace = workspace(tmp_path)
    provider_change = change({"kind": "symbol", "name": "Client.send"})
    service = RepositoryIntelligenceService()
    now = datetime(2026, 8, 5, tzinfo=UTC)

    first = service.analyze(repository(), repo_workspace, provider_change, now=now)
    second = service.analyze(repository(), repo_workspace, provider_change, now=now)

    assert first.snapshot.id == second.snapshot.id
    assert first.snapshot.inventory_digest == second.snapshot.inventory_digest
    assert first.impact.assessment_id == second.impact.assessment_id
