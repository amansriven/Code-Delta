import hashlib
import json
from pathlib import Path

import httpx
import pytest

from app.control_plane.models import MigrationEvidence
from app.github_publishing.models import (
    GitHubCredentials,
    PublicationContext,
    PublicationEdit,
    PublicationRecord,
)
from app.github_publishing.patch import PublicationPolicyError, load_publication_edits
from app.github_publishing.publisher import (
    BranchCollision,
    GitHubPullRequestPublisher,
    PermissionDenied,
    RemoteStateConflict,
    StaleBase,
)
from app.ingestion.storage import FilesystemArtifactStore
from app.repository_intelligence.models import RepositoryRef

EXAMPLE = (
    Path(__file__).parent.parent
    / "docs/architecture/examples/migration-evidence.example.json"
)


def evidence() -> MigrationEvidence:
    return MigrationEvidence.model_validate_json(EXAMPLE.read_text())


def context(**record_updates) -> PublicationContext:
    item = evidence()
    defaults = {
        "id": "publication-1",
        "migration_id": item.migration_id,
        "last_attempt_id": item.attempt_id,
        "status": "publishing",
        "branch": "delta-code/migration-abc123",
        "base_sha": item.repository.base_commit_sha,
        "patch_sha256": item.patch.sha256,
    }
    defaults.update(record_updates)
    return PublicationContext(
        workspace_id="workspace-1",
        repository=RepositoryRef(
            id=item.repository.id,
            workspace_id="workspace-1",
            full_name=item.repository.full_name,
            clone_url=f"https://github.com/{item.repository.full_name}.git",
            default_branch="main",
            installation_id=7,
        ),
        evidence=item,
        artifact_object_ref="sha256/dd/" + "d" * 64,
        record=PublicationRecord(**defaults),
    )


class Broker:
    def __init__(self, permissions=None):
        self.permissions = permissions or {
            "contents": "write",
            "pull_requests": "write",
            "checks": "write",
        }

    def resolve(self, handle):
        assert handle == "github-installation:7"
        return GitHubCredentials(token="short-lived", permissions=self.permissions)


class Progress:
    def __init__(self):
        self.events = []

    def record_tree(self, sha):
        self.events.append(("tree", sha))

    def record_commit(self, sha):
        self.events.append(("commit", sha))

    def record_branch(self, sha, action):
        self.events.append(("branch", action, sha))

    def record_pull_request(self, number, node_id, url, action):
        self.events.append(("pull", action, number, node_id, url))

    def record_check(self, check_id):
        self.events.append(("check", check_id))


def test_patch_loader_preserves_exact_canonical_edits(tmp_path: Path):
    payload = {
        "schema_version": "1.0",
        "edits": [
            {
                "path": "src/client.py",
                "expected_sha256": "a" * 64,
                "content": "new_call()\n",
                "plan_step_ids": ["step-1"],
            }
        ],
    }
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(content).hexdigest()
    store = FilesystemArtifactStore(tmp_path)
    object_ref = store.put(content, digest)

    edits = load_publication_edits(store, object_ref, digest)

    assert edits[0].content.encode() == b"new_call()\n"


def test_patch_loader_rejects_noncanonical_or_changed_artifact(tmp_path: Path):
    content = b'{"schema_version":"1.0", "edits":[]}'
    digest = hashlib.sha256(content).hexdigest()
    store = FilesystemArtifactStore(tmp_path)
    object_ref = store.put(content, digest)

    with pytest.raises(PublicationPolicyError):
        load_publication_edits(store, object_ref, digest)


def test_publisher_commits_exact_tree_and_opens_draft_with_check():
    requests = []
    base_sha = evidence().repository.base_commit_sha

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        path = request.url.path
        if path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": base_sha}})
        if "/git/ref/heads/delta-code/" in path:
            return httpx.Response(404, json={"message": "Not Found"})
        if path.endswith(f"/git/commits/{base_sha}"):
            return httpx.Response(200, json={"tree": {"sha": "base-tree"}})
        if path.endswith("/git/trees/base-tree"):
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [{"path": "src/client.py", "type": "blob", "mode": "100755"}],
                },
            )
        if path.endswith("/git/trees"):
            assert body["tree"] == [
                {
                    "path": "src/client.py",
                    "mode": "100755",
                    "type": "blob",
                    "content": "new_call()\n",
                }
            ]
            return httpx.Response(201, json={"sha": "new-tree"})
        if path.endswith("/git/commits"):
            assert body["parents"] == [base_sha]
            assert body["tree"] == "new-tree"
            return httpx.Response(201, json={"sha": "new-commit"})
        if path.endswith("/git/refs"):
            assert body["sha"] == "new-commit"
            return httpx.Response(201, json={"object": {"sha": "new-commit"}})
        if path.endswith("/pulls"):
            assert body["draft"] is True
            assert body["maintainer_can_modify"] is False
            return httpx.Response(
                201,
                json={
                    "number": 17,
                    "node_id": "PR_node",
                    "html_url": "https://github.com/acme/inventory-api/pull/17",
                    "draft": True,
                },
            )
        if path.endswith("/check-runs"):
            assert body["head_sha"] == "new-commit"
            assert body["conclusion"] == "success"
            return httpx.Response(201, json={"id": 99})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    progress = Progress()
    result = GitHubPullRequestPublisher(
        Broker(), client=httpx.Client(transport=httpx.MockTransport(handler))
    ).publish(
        context(),
        [
            PublicationEdit(
                path="src/client.py",
                expected_sha256="a" * 64,
                content="new_call()\n",
                plan_step_ids=["step-1"],
            )
        ],
        progress,
    )

    assert result.commit_sha == "new-commit"
    assert result.pull_number == 17
    assert progress.events == [
        ("tree", "new-tree"),
        ("commit", "new-commit"),
        ("branch", "created", "new-commit"),
        (
            "pull",
            "created",
            17,
            "PR_node",
            "https://github.com/acme/inventory-api/pull/17",
        ),
        ("check", 99),
    ]
    assert all(value != "short-lived" for _, _, body in requests for value in (body or {}).values())


def test_publisher_fails_before_writes_when_base_is_stale():
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json={"object": {"sha": "f" * 40}})

    publisher = GitHubPullRequestPublisher(
        Broker(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(StaleBase):
        publisher.publish(context(), [], Progress())

    assert calls == ["GET"]


def test_publisher_rejects_branch_collision_before_git_object_writes():
    calls = []
    base_sha = evidence().repository.base_commit_sha

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": base_sha}})
        return httpx.Response(200, json={"object": {"sha": "f" * 40}})

    publisher = GitHubPullRequestPublisher(
        Broker(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(BranchCollision):
        publisher.publish(context(), [], Progress())

    assert all(method == "GET" for method, _path in calls)


def test_publisher_requires_all_expanded_installation_permissions():
    publisher = GitHubPullRequestPublisher(Broker({"contents": "write"}))

    with pytest.raises(PermissionDenied):
        publisher.publish(context(), [], Progress())


def test_revision_refuses_to_overwrite_a_ready_or_changed_pull_request():
    base_sha = evidence().repository.base_commit_sha
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": base_sha}})
        if request.url.path.endswith("/pulls/17"):
            return httpx.Response(
                200,
                json={"state": "open", "draft": False, "head": {"sha": "old-head"}},
            )
        raise AssertionError("publisher wrote before validating the existing draft")

    publisher = GitHubPullRequestPublisher(
        Broker(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(RemoteStateConflict):
        publisher.publish(
            context(
                pull_number=17,
                pull_node_id="PR_node",
                pull_url="https://github.com/acme/inventory-api/pull/17",
                remote_head_sha="old-head",
            ),
            [],
            Progress(),
        )

    assert calls == [
        ("GET", "/repos/acme/inventory-api/git/ref/heads/main"),
        ("GET", "/repos/acme/inventory-api/pulls/17"),
    ]


def test_approve_marks_draft_ready_without_merging():
    requests = []

    def handler(request):
        body = json.loads(request.content) if request.content else None
        requests.append((request.url.path, body))
        if request.url.path.endswith("/pulls/17"):
            return httpx.Response(
                200,
                json={"state": "open", "draft": True, "head": {"sha": "head-sha"}},
            )
        if request.url.path == "/graphql":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "markPullRequestReadyForReview": {
                            "pullRequest": {"id": "PR_node", "isDraft": False}
                        }
                    }
                },
            )
        raise AssertionError(request.url)

    GitHubPullRequestPublisher(
        Broker(), client=httpx.Client(transport=httpx.MockTransport(handler))
    ).synchronize_action(
        repository_full_name="acme/inventory-api",
        installation_id=7,
        pull_number=17,
        pull_node_id="PR_node",
        expected_head_sha="head-sha",
        action="approve",
    )

    assert requests[1][0] == "/graphql"
    assert "markPullRequestReadyForReview" in requests[1][1]["query"]
    assert "merge" not in requests[1][1]["query"].lower()
