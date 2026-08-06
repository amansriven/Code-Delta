"""Safe, ephemeral Git workspace acquisition and deterministic hashing."""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from app.github_client import get_installation_token
from app.repo_fetch import fetch_ref
from app.repository_intelligence.models import RepositoryRef, RepositoryWorkspace


IGNORED_DIRECTORIES = {
    ".git", ".venv", "node_modules", "vendor", "dist", "build", "__pycache__", ".next"
}


class WorkspacePolicyError(ValueError):
    pass


class CredentialBroker(Protocol):
    def resolve(self, credential_handle: str) -> str: ...


class GitHubInstallationCredentialBroker:
    def resolve(self, credential_handle: str) -> str:
        prefix = "github-installation:"
        if not credential_handle.startswith(prefix):
            raise WorkspacePolicyError("unsupported credential handle")
        try:
            installation_id = int(credential_handle.removeprefix(prefix))
        except ValueError as exc:
            raise WorkspacePolicyError("invalid credential handle") from exc
        return get_installation_token(installation_id)


def _validate_clone_url(repository: RepositoryRef) -> None:
    parsed = urlparse(str(repository.clone_url))
    expected_path = f"/{repository.full_name}.git"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise WorkspacePolicyError("repository clone URL does not match its GitHub identity")


def _walk_entries(root: Path):
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            ordered = sorted(entries, key=lambda item: item.name, reverse=True)
        for entry in ordered:
            relative = Path(entry.path).relative_to(root).as_posix()
            if entry.is_symlink():
                yield relative, "symlink", os.readlink(entry.path).encode()
            elif entry.is_dir(follow_symlinks=False):
                if entry.name not in IGNORED_DIRECTORIES:
                    pending.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                yield relative, "file", Path(entry.path)


def workspace_fingerprint(
    root: Path,
    *,
    max_files: int = 50_000,
    max_bytes: int = 200_000_000,
) -> tuple[str, int, int, int]:
    digest = hashlib.sha256()
    file_count = 0
    size_bytes = 0
    symlink_count = 0
    for relative, entry_type, value in sorted(_walk_entries(root), key=lambda item: item[0]):
        digest.update(entry_type.encode() + b"\0" + relative.encode() + b"\0")
        if entry_type == "symlink":
            symlink_count += 1
            digest.update(value)
            continue
        file_count += 1
        if file_count > max_files:
            raise WorkspacePolicyError("repository exceeds file-count limit")
        path = value
        size = path.stat(follow_symlinks=False).st_size
        size_bytes += size
        if size_bytes > max_bytes:
            raise WorkspacePolicyError("repository exceeds byte limit")
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    return f"sha256:{digest.hexdigest()}", file_count, size_bytes, symlink_count


class GitRepositoryWorkspaceProvider:
    provider_version = "1.0.0"

    def __init__(self, credential_broker: CredentialBroker):
        self.credential_broker = credential_broker

    def materialize(
        self,
        repository: RepositoryRef,
        ref: str,
        credential_handle: str,
    ) -> RepositoryWorkspace:
        _validate_clone_url(repository)
        token = self.credential_broker.resolve(credential_handle)
        root = fetch_ref(str(repository.clone_url), ref, token)
        try:
            commit_sha = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if len(commit_sha) != 40 or any(character not in "0123456789abcdef" for character in commit_sha):
                raise WorkspacePolicyError("Git returned an invalid commit SHA")
            digest, file_count, size_bytes, symlink_count = workspace_fingerprint(root)
            return RepositoryWorkspace(
                repository_id=repository.id,
                root=str(root),
                commit_sha=commit_sha,
                content_digest=digest,
                file_count=file_count,
                size_bytes=size_bytes,
                symlink_count=symlink_count,
            )
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise

    def cleanup(self, workspace: RepositoryWorkspace) -> None:
        shutil.rmtree(Path(workspace.root), ignore_errors=True)
