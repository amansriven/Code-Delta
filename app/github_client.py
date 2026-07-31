"""GitHub App auth + posting results (spec Phase 3).

Requires a GitHub App to already exist (see README for setup steps) and
GITHUB_APP_ID / GITHUB_PRIVATE_KEY env vars to be set. Not exercised by the
test suite — there's no way to test real GitHub API calls without a real App.
"""

import os
import time

import httpx
import jwt

GITHUB_API = "https://api.github.com"


def _app_jwt() -> str:
    app_id = os.environ["GITHUB_APP_ID"]
    private_key = os.environ["GITHUB_PRIVATE_KEY"]
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": app_id}
    return jwt.encode(payload, private_key, algorithm="RS256")


def get_installation_token(installation_id: int) -> str:
    resp = httpx.post(
        f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {_app_jwt()}",
            "Accept": "application/vnd.github+json",
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def _format_summary(findings: list[dict]) -> str:
    if not findings:
        return (
            "No regressions reproduced. All generated edge-case requests "
            "behaved the same on both branches."
        )

    lines = [
        f"Reproduced {len(findings)} finding(s) by running generated edge-case "
        "requests against base and PR branches:\n"
    ]
    for f in findings:
        req = f["request"]
        lines.append(f"### `{f['kind']}` — {req['method']} {req['path']} ({f['case']})")
        lines.append(f"- Request body: `{req.get('json')}`")
        lines.append(
            f"- Base response: `{f['base_response']['status_code']}` — {f['base_response']['body']}"
        )
        lines.append(
            f"- PR response: `{f['pr_response']['status_code']}` — {f['pr_response']['body']}"
        )
        lines.append("")
    return "\n".join(lines)


def post_check_run(
    installation_id: int,
    repo: str,
    head_sha: str,
    findings: list[dict],
) -> None:
    """Post a single Check Run on the PR's head commit summarizing findings."""
    token = get_installation_token(installation_id)
    has_regressions = any(f["kind"] == "regression" for f in findings)
    conclusion = "failure" if has_regressions else "success"

    resp = httpx.post(
        f"{GITHUB_API}/repos/{repo}/check-runs",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "name": "CodeDelta API Verifier",
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": conclusion,
            "output": {
                "title": f"{len(findings)} finding(s)" if findings else "No regressions found",
                "summary": _format_summary(findings),
            },
        },
        timeout=10.0,
    )
    resp.raise_for_status()
