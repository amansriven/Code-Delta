from pathlib import Path

import pytest

from app.repository_intelligence.models import RepositoryRef
from app.repository_intelligence.workspace import (
    GitRepositoryWorkspaceProvider,
    WorkspacePolicyError,
    workspace_fingerprint,
)


class RecordingBroker:
    def __init__(self):
        self.handles = []

    def resolve(self, credential_handle: str) -> str:
        self.handles.append(credential_handle)
        return "secret-token"


def repository(clone_url: str = "https://github.com/acme/example.git") -> RepositoryRef:
    return RepositoryRef(
        id="repo-1",
        workspace_id="workspace-1",
        full_name="acme/example",
        clone_url=clone_url,
        default_branch="main",
        installation_id=7,
    )


def test_workspace_fingerprint_is_deterministic_and_content_addressed(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('one')\n")

    first = workspace_fingerprint(tmp_path)
    second = workspace_fingerprint(tmp_path)
    (tmp_path / "src" / "app.py").write_text("print('two')\n")
    changed = workspace_fingerprint(tmp_path)

    assert first == second
    assert first[0] != changed[0]
    assert first[1:] == (1, 13, 0)


def test_workspace_fingerprint_records_but_never_follows_symlinks(tmp_path: Path):
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("do not read")
    (tmp_path / "link").symlink_to(outside)

    digest, file_count, size_bytes, symlinks = workspace_fingerprint(tmp_path)

    assert digest.startswith("sha256:")
    assert (file_count, size_bytes, symlinks) == (0, 0, 1)


def test_workspace_limits_fail_closed(tmp_path: Path):
    (tmp_path / "one.py").write_text("1")
    (tmp_path / "two.py").write_text("2")

    with pytest.raises(WorkspacePolicyError, match="file-count"):
        workspace_fingerprint(tmp_path, max_files=1)
    with pytest.raises(WorkspacePolicyError, match="byte limit"):
        workspace_fingerprint(tmp_path, max_bytes=1)


def test_clone_identity_is_validated_before_credentials_are_resolved():
    broker = RecordingBroker()
    provider = GitRepositoryWorkspaceProvider(broker)

    with pytest.raises(WorkspacePolicyError, match="does not match"):
        provider.materialize(
            repository("https://github.com/acme/another.git"),
            "main",
            "github-installation:7",
        )

    assert broker.handles == []
