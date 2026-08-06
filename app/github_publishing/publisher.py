"""Narrow GitHub App publisher for exact validated patch artifacts."""

import json
from typing import Any, Protocol
from urllib.parse import quote, urlparse

import httpx

from app.control_plane.models import MigrationEvidence
from app.github_client import get_installation_credentials

from .models import GitHubCredentials, PublicationContext, PublicationEdit, PublicationResult

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"
MAX_GITHUB_RESPONSE_BYTES = 2_000_000


class PublishingError(RuntimeError):
    code = "github_publication_failed"


class PermissionDenied(PublishingError):
    code = "github_write_permissions_missing"


class StaleBase(PublishingError):
    code = "github_base_advanced"


class BranchCollision(PublishingError):
    code = "github_branch_collision"


class RemoteStateConflict(PublishingError):
    code = "github_remote_state_conflict"


class PublicationProgress(Protocol):
    def record_tree(self, tree_sha: str) -> None: ...
    def record_commit(self, commit_sha: str) -> None: ...
    def record_branch(self, head_sha: str, action: str) -> None: ...
    def record_pull_request(
        self, number: int, node_id: str, url: str, action: str
    ) -> None: ...
    def record_check(self, check_run_id: int) -> None: ...


class GitHubInstallationCredentialBroker:
    def resolve(self, credential_handle: str) -> GitHubCredentials:
        prefix = "github-installation:"
        if not credential_handle.startswith(prefix):
            raise PermissionDenied("unsupported credential handle")
        try:
            installation_id = int(credential_handle.removeprefix(prefix))
        except ValueError as exc:
            raise PermissionDenied("invalid credential handle") from exc
        credentials = get_installation_credentials(installation_id)
        return GitHubCredentials(
            token=credentials.token,
            permissions=credentials.permissions,
        )


class GitHubApi:
    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=httpx.Timeout(30, connect=5))
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> dict[str, Any] | None:
        with self.client.stream(
            method,
            f"{GITHUB_API}{path}",
            headers=self.headers,
            json=body,
        ) as response:
            if allow_404 and response.status_code == 404:
                return None
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_GITHUB_RESPONSE_BYTES:
                    raise PublishingError("GitHub response exceeds limit")
        if not content:
            return {}
        try:
            payload = json.loads(content)
        except ValueError as exc:
            raise PublishingError("GitHub returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise PublishingError("GitHub returned an invalid response")
        return payload

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        with self.client.stream(
            "POST",
            f"{GITHUB_API}/graphql",
            headers=self.headers,
            json={"query": query, "variables": variables},
        ) as response:
            response.raise_for_status()
            content = response.read()
        if len(content) > MAX_GITHUB_RESPONSE_BYTES:
            raise PublishingError("GitHub GraphQL response exceeds limit")
        try:
            payload = json.loads(content)
        except ValueError as exc:
            raise PublishingError("GitHub returned invalid GraphQL JSON") from exc
        if not isinstance(payload, dict) or payload.get("errors"):
            raise PublishingError("GitHub rejected the pull request mutation")
        return payload


def _repository_path(full_name: str) -> str:
    owner, name = full_name.split("/", 1)
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def _validate_pull_url(value: str, full_name: str, number: int) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != f"/{full_name}/pull/{number}"
    ):
        raise PublishingError("GitHub returned an invalid pull request URL")


def _require_permissions(credentials: GitHubCredentials) -> None:
    required = {"contents", "pull_requests", "checks"}
    missing = sorted(
        permission
        for permission in required
        if credentials.permissions.get(permission) != "write"
    )
    if missing:
        raise PermissionDenied("GitHub App installation has not approved required writes")


def _render_title(evidence: MigrationEvidence) -> str:
    return f"Migrate: {evidence.plan.summary}"[:240]


def _render_body(evidence: MigrationEvidence) -> str:
    files = "\n".join(f"- `{item.path}` ({item.change_type})" for item in evidence.patch.files)
    checks = "\n".join(
        f"- `{item.kind}`: **{item.status}** — {item.summary}"
        for item in evidence.verification_checks
    )
    sources = (
        f"- Change event: `{evidence.change_event_id}`\n"
        f"- Impact assessment: `{evidence.impact.assessment_id}`"
    )
    body = (
        "## Delta Code migration\n\n"
        f"{evidence.plan.summary}\n\n"
        f"**Attempt:** `{evidence.attempt_id}`  \n"
        f"**Base commit:** `{evidence.repository.base_commit_sha}`  \n"
        f"**Patch SHA-256:** `{evidence.patch.sha256}`\n\n"
        "### Changed files\n"
        f"{files}\n\n"
        "### Deterministic verification\n"
        f"{checks}\n\n"
        "### Review\n"
        f"{evidence.review.summary}\n\n"
        f"**Recommendation:** {evidence.recommendation.action} — "
        f"{evidence.recommendation.rationale}\n\n"
        "### Source evidence\n"
        f"{sources}\n\n"
        "---\nGenerated from a stored, sandbox-verified patch. This pull request is draft; "
        "Delta Code never merges automatically."
    )
    return body[:60_000]


class GitHubPullRequestPublisher:
    def __init__(
        self,
        credential_broker: GitHubInstallationCredentialBroker,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.credential_broker = credential_broker
        self.client = client

    def publish(
        self,
        context: PublicationContext,
        edits: list[PublicationEdit],
        progress: PublicationProgress,
    ) -> PublicationResult:
        credentials = self.credential_broker.resolve(
            f"github-installation:{context.repository.installation_id}"
        )
        _require_permissions(credentials)
        api = GitHubApi(credentials.token, self.client)
        prefix = _repository_path(context.repository.full_name)
        evidence = context.evidence
        record = context.record

        base_ref = api.request(
            "GET",
            f"{prefix}/git/ref/heads/{quote(evidence.repository.base_branch, safe='')}",
        )
        if not base_ref or base_ref.get("object", {}).get("sha") != record.base_sha:
            raise StaleBase("repository base branch no longer matches the verified snapshot")
        if record.pull_number is not None:
            existing_pull = api.request("GET", f"{prefix}/pulls/{record.pull_number}") or {}
            if (
                existing_pull.get("state") != "open"
                or existing_pull.get("draft") is not True
                or existing_pull.get("head", {}).get("sha") != record.remote_head_sha
            ):
                raise RemoteStateConflict("existing draft changed outside Delta Code")
        branch_path = f"{prefix}/git/ref/heads/{quote(record.branch, safe='')}"
        branch_ref = api.request("GET", branch_path, allow_404=True)
        current_head = (branch_ref or {}).get("object", {}).get("sha")
        if record.pull_number is None and branch_ref:
            if not record.commit_sha or current_head != record.commit_sha:
                raise BranchCollision("publication branch already exists at another commit")
        if record.pull_number is not None and current_head not in {
            record.remote_head_sha,
            record.commit_sha,
        }:
            raise RemoteStateConflict("draft branch changed outside Delta Code")
        base_commit = api.request("GET", f"{prefix}/git/commits/{record.base_sha}")
        base_tree_sha = (base_commit or {}).get("tree", {}).get("sha")
        if not isinstance(base_tree_sha, str):
            raise PublishingError("GitHub base commit omitted its tree")
        base_tree = api.request("GET", f"{prefix}/git/trees/{base_tree_sha}?recursive=1")
        if not base_tree or base_tree.get("truncated"):
            raise PublishingError("GitHub base tree is unavailable or truncated")
        modes = {
            item.get("path"): item.get("mode")
            for item in base_tree.get("tree", [])
            if isinstance(item, dict) and item.get("type") == "blob"
        }
        tree_entries = []
        for edit in edits:
            existing_mode = modes.get(edit.path)
            if edit.expected_sha256 is not None and existing_mode not in {"100644", "100755"}:
                raise RemoteStateConflict("validated patch target is absent from the base tree")
            if edit.expected_sha256 is None and existing_mode is not None:
                raise RemoteStateConflict("validated new file already exists in the base tree")
            tree_entries.append(
                {
                    "path": edit.path,
                    "mode": existing_mode or "100644",
                    "type": "blob",
                    "content": edit.content,
                }
            )

        tree_sha = record.tree_sha
        if not tree_sha:
            tree = api.request(
                "POST",
                f"{prefix}/git/trees",
                body={"base_tree": base_tree_sha, "tree": tree_entries},
            )
            tree_sha = (tree or {}).get("sha")
            if not isinstance(tree_sha, str):
                raise PublishingError("GitHub did not return the created tree SHA")
            progress.record_tree(tree_sha)

        commit_sha = record.commit_sha
        if not commit_sha:
            commit_identity = {
                "name": "Delta Code",
                "email": "delta-code@users.noreply.github.com",
                "date": evidence.completed_at.isoformat(),
            }
            commit = api.request(
                "POST",
                f"{prefix}/git/commits",
                body={
                    "message": f"Delta Code migration {context.record.migration_id}",
                    "tree": tree_sha,
                    "parents": [record.base_sha],
                    "author": commit_identity,
                    "committer": commit_identity,
                },
            )
            commit_sha = (commit or {}).get("sha")
            if not isinstance(commit_sha, str):
                raise PublishingError("GitHub did not return the created commit SHA")
            progress.record_commit(commit_sha)

        if record.pull_number is None:
            if not branch_ref:
                api.request(
                    "POST",
                    f"{prefix}/git/refs",
                    body={"ref": f"refs/heads/{record.branch}", "sha": commit_sha},
                )
                progress.record_branch(commit_sha, "created")
            elif record.remote_head_sha != commit_sha:
                progress.record_branch(commit_sha, "reconciled")
        else:
            if current_head != commit_sha:
                api.request(
                    "PATCH",
                    f"{prefix}/git/refs/heads/{quote(record.branch, safe='')}",
                    body={"sha": commit_sha, "force": True},
                )
                progress.record_branch(commit_sha, "updated")

        title = _render_title(evidence)
        body = _render_body(evidence)
        pull_number = record.pull_number
        pull_node_id = record.pull_node_id
        pull_url = record.pull_url
        if pull_number is None:
            pull = api.request(
                "POST",
                f"{prefix}/pulls",
                body={
                    "title": title,
                    "body": body,
                    "head": record.branch,
                    "base": evidence.repository.base_branch,
                    "draft": True,
                    "maintainer_can_modify": False,
                },
            ) or {}
            pull_number = pull.get("number")
            pull_node_id = pull.get("node_id")
            pull_url = pull.get("html_url")
            if not isinstance(pull_number, int) or not all(
                isinstance(item, str) for item in (pull_node_id, pull_url)
            ) or pull.get("draft") is not True:
                raise PublishingError("GitHub did not return a valid draft pull request")
            _validate_pull_url(pull_url, context.repository.full_name, pull_number)
            progress.record_pull_request(pull_number, pull_node_id, pull_url, "created")
        else:
            pull = api.request("GET", f"{prefix}/pulls/{pull_number}") or {}
            if pull.get("head", {}).get("sha") != commit_sha:
                raise RemoteStateConflict("draft pull request head does not match publication")
            updated = api.request(
                "PATCH",
                f"{prefix}/pulls/{pull_number}",
                body={"title": title, "body": body},
            ) or {}
            pull_node_id = updated.get("node_id") or pull_node_id
            pull_url = updated.get("html_url") or pull_url
            if not isinstance(pull_node_id, str) or not isinstance(pull_url, str):
                raise PublishingError("GitHub did not return the updated pull request")
            _validate_pull_url(pull_url, context.repository.full_name, pull_number)
            progress.record_pull_request(pull_number, pull_node_id, pull_url, "updated")

        check_run_id = record.check_run_id
        if check_run_id is None:
            check = api.request(
                "POST",
                f"{prefix}/check-runs",
                body={
                    "name": "Delta Code Migration Verification",
                    "head_sha": commit_sha,
                    "status": "completed",
                    "conclusion": "success",
                    "external_id": f"{record.migration_id}:{record.last_attempt_id}",
                    "output": {
                        "title": "Sandbox verification passed",
                        "summary": "All stored deterministic checks passed for this exact patch.",
                    },
                },
            ) or {}
            check_run_id = check.get("id")
            if not isinstance(check_run_id, int):
                raise PublishingError("GitHub did not return the check run id")
            progress.record_check(check_run_id)

        return PublicationResult(
            tree_sha=tree_sha,
            commit_sha=commit_sha,
            branch=record.branch,
            pull_number=pull_number,
            pull_node_id=pull_node_id,
            pull_url=pull_url,
            check_run_id=check_run_id,
        )

    def synchronize_action(
        self,
        *,
        repository_full_name: str,
        installation_id: int,
        pull_number: int,
        pull_node_id: str,
        expected_head_sha: str,
        action: str,
    ) -> None:
        credentials = self.credential_broker.resolve(
            f"github-installation:{installation_id}"
        )
        if credentials.permissions.get("pull_requests") != "write":
            raise PermissionDenied("GitHub App installation lacks pull-request write access")
        api = GitHubApi(credentials.token, self.client)
        prefix = _repository_path(repository_full_name)
        pull = api.request("GET", f"{prefix}/pulls/{pull_number}") or {}
        if pull.get("head", {}).get("sha") != expected_head_sha:
            raise RemoteStateConflict("pull request head changed outside Delta Code")
        if action == "approve":
            if pull.get("state") != "open":
                raise RemoteStateConflict("pull request is not open")
            if pull.get("draft") is False:
                return
            api.graphql(
                "mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id})"
                "{pullRequest{id isDraft}}}",
                {"id": pull_node_id},
            )
            return
        if action == "decline":
            if pull.get("state") == "closed":
                return
            api.request(
                "PATCH",
                f"{prefix}/pulls/{pull_number}",
                body={"state": "closed"},
            )
            return
        raise ValueError("unsupported pull request action")
