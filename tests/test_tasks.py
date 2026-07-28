from app import github_client, tasks


def test_github_run_uses_installation_token_and_pull_ref(monkeypatch, tmp_path):
    run = {
        "clone_url": "https://github.com/acme/private-api.git",
        "base_ref": "main",
        "base_sha": "base-commit",
        "head_ref": "feature",
        "head_sha": "head-commit",
        "installation_id": 17,
        "repo": "acme/private-api",
        "pr_number": 9,
    }
    fetches = []
    check_runs = []

    monkeypatch.setattr(tasks, "_get_run", lambda _run_id: run)
    monkeypatch.setattr(github_client, "get_installation_token", lambda _installation_id: "token")

    def fake_fetch(clone_url, ref, token):
        fetches.append((clone_url, ref, token))
        checkout = tmp_path / f"checkout-{len(fetches)}"
        checkout.mkdir()
        return checkout

    monkeypatch.setattr(tasks, "fetch_ref", fake_fetch)
    monkeypatch.setattr(tasks, "compare", lambda _base, _head: [])
    monkeypatch.setattr(tasks, "_set_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        github_client,
        "post_check_run",
        lambda installation_id, repo, head_sha, findings: check_runs.append(
            (installation_id, repo, head_sha, findings)
        ),
    )

    tasks._run_comparison(31)

    assert fetches == [
        ("https://github.com/acme/private-api.git", "base-commit", "token"),
        ("https://github.com/acme/private-api.git", "refs/pull/9/head", "token"),
    ]
    assert check_runs == [(17, "acme/private-api", "head-commit", [])]
