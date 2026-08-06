"""Immutable, content-addressed artifact storage."""

import hashlib
import os
from pathlib import Path
from typing import Protocol


class ArtifactIntegrityError(ValueError):
    pass


class ArtifactStore(Protocol):
    retention_days: int

    def put(self, content: bytes, sha256: str) -> str: ...
    def read(self, object_ref: str) -> bytes: ...


class FilesystemArtifactStore:
    """MVP backend intended for an encrypted persistent volume.

    Object names are derived only from verified digests. Existing objects are
    never overwritten, and their bytes are re-verified on every read.
    """

    def __init__(self, root: Path, *, retention_days: int = 90):
        if retention_days < 1:
            raise ValueError("retention_days must be positive")
        self.root = root.resolve()
        self.retention_days = retention_days
        self.root.mkdir(parents=True, exist_ok=True, mode=0o750)

    def _path(self, sha256: str) -> Path:
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise ArtifactIntegrityError("invalid SHA-256 digest")
        return self.root / "sha256" / sha256[:2] / sha256

    def put(self, content: bytes, sha256: str) -> str:
        actual = hashlib.sha256(content).hexdigest()
        if actual != sha256.lower():
            raise ArtifactIntegrityError("artifact digest does not match content")
        path = self._path(actual)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ArtifactIntegrityError("immutable artifact content mismatch") from None
        else:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
        return f"sha256/{actual[:2]}/{actual}"

    def read(self, object_ref: str) -> bytes:
        parts = Path(object_ref).parts
        if len(parts) != 3 or parts[0] != "sha256" or parts[1] != parts[2][:2]:
            raise ArtifactIntegrityError("invalid object reference")
        path = self._path(parts[2])
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != parts[2]:
            raise ArtifactIntegrityError("stored artifact failed integrity verification")
        return content
