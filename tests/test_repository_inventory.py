from pathlib import Path

from app.repository_intelligence.inventory import RepositoryInventoryBuilder
from app.repository_intelligence.models import RepositoryWorkspace
from app.repository_intelligence.workspace import workspace_fingerprint


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


def test_inventory_detects_languages_and_python_manifests(tmp_path: Path):
    (tmp_path / "app.py").write_text("import httpx\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["httpx>=0.27", "Example_SDK~=2.0"]\n'
    )
    (tmp_path / "requirements-dev.txt").write_text("pytest==8.3.1\n-r base.txt\n")

    result = RepositoryInventoryBuilder().build(workspace(tmp_path))

    assert [(item.language, item.file_count) for item in result.languages] == [("Python", 1)]
    assert {item.package for item in result.dependencies} == {"example-sdk", "httpx", "pytest"}
    assert all(item.parsed for item in result.manifests)
    assert result.capabilities[0].supported is True


def test_inventory_reads_npm_manifest_and_lockfile_without_installing(tmp_path: Path):
    (tmp_path / "index.ts").write_text("export const value = 1\n")
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"stripe":"^18.0.0"},"devDependencies":{"vite":"^7.0.0"}}'
    )
    (tmp_path / "package-lock.json").write_text(
        '{"lockfileVersion":3,"packages":{"node_modules/stripe":{"version":"18.1.0"}}}'
    )

    result = RepositoryInventoryBuilder().build(workspace(tmp_path))

    assert [(item.language, item.file_count) for item in result.languages] == [("TypeScript", 1)]
    assert {(item.package, item.detection_method) for item in result.dependencies} == {
        ("stripe", "manifest"),
        ("stripe", "lockfile"),
        ("vite", "manifest"),
    }
    assert result.capabilities[0].supported is True
    assert "TypeScript" in result.capabilities[0].languages


def test_inventory_digest_is_stable_and_changes_with_inventory(tmp_path: Path):
    source = tmp_path / "app.py"
    source.write_text("value = 1\n")
    builder = RepositoryInventoryBuilder()

    first = builder.build(workspace(tmp_path))
    second = builder.build(workspace(tmp_path))
    source.write_text("value = 2\n")
    changed = builder.build(workspace(tmp_path))

    assert first.inventory_digest == second.inventory_digest
    assert first.inventory_digest != changed.inventory_digest
