import subprocess

import pytest

from app import repo_fetch


def test_fetch_errors_never_include_installation_token(monkeypatch):
    token = "installation-secret"
    calls = 0

    def fake_run(command, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise subprocess.CalledProcessError(
                128,
                command,
                stderr=f"authentication failed for x-access-token:{token}",
            )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(repo_fetch.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as error:
        repo_fetch.fetch_ref("https://github.com/acme/private-api.git", "main", token)

    assert token not in str(error.value)
    assert "[redacted]" in str(error.value)
