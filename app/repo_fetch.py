import subprocess
import tempfile
from pathlib import Path


def fetch_ref(clone_url: str, ref: str, token: str | None = None) -> Path:
    """Clone a single ref (branch name or commit SHA) of a repo into a fresh
    temp directory and return its path. Shallow (depth 1) — v1 only needs the
    working tree at that ref, not history.
    """
    url = clone_url
    if token:
        # GitHub App installation tokens authenticate over HTTPS as the
        # username, with any (or no) password.
        url = clone_url.replace("https://", f"https://x-access-token:{token}@")

    dest = Path(tempfile.mkdtemp(prefix="codedelta-"))
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", "--branch", ref, url, str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest
