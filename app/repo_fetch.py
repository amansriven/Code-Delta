import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote


def fetch_ref(clone_url: str, ref: str, token: str | None = None) -> Path:
    """Clone a single ref (branch name or commit SHA) of a repo into a fresh
    temp directory and return its path. Shallow (depth 1) — v1 only needs the
    working tree at that ref, not history.
    """
    url = clone_url
    if token:
        # Installation tokens authenticate GitHub HTTPS clones. Pass the URL
        # only to fetch (rather than saving it as a remote) so the checked-out
        # application cannot read the credential from .git/config.
        encoded_token = quote(token, safe="")
        url = clone_url.replace("https://", f"https://x-access-token:{encoded_token}@")

    dest = Path(tempfile.mkdtemp(prefix="codedelta-"))
    try:
        subprocess.run(
            ["git", "init", "--quiet", str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            subprocess.run(
                ["git", "-C", str(dest), "fetch", "--quiet", "--depth", "1", url, ref],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr or "git did not return an error message"
            if token:
                detail = detail.replace(token, "[redacted]").replace(
                    encoded_token, "[redacted]"
                )
            raise RuntimeError(f"could not fetch {clone_url} at {ref}: {detail}") from None
        subprocess.run(
            ["git", "-C", str(dest), "checkout", "--quiet", "--detach", "FETCH_HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return dest
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
