import hashlib
import json
from pathlib import Path

import pytest

from app.control_plane.fakes import (
    AnalyzerFixture,
    FakePublisher,
    FakeSandboxExecutor,
    FixtureAnalyzer,
    PublicationRequest,
    SandboxRequest,
    redact_data,
)
from app.control_plane.store import IdempotencyConflictError

ANALYZER_FIXTURES = Path(__file__).parent / "fixtures" / "analyzers"


@pytest.mark.parametrize("conclusion", ["affected", "unaffected", "uncertain", "unsupported"])
def test_analyzer_fixture_preserves_supported_outcomes(conclusion):
    payload = json.loads((ANALYZER_FIXTURES / f"{conclusion}.json").read_text())

    result = FixtureAnalyzer().assess(AnalyzerFixture.model_validate(payload))

    assert result["conclusion"] == conclusion
    assert result["coverage"]["supported"] is payload["supported"]


def test_analyzer_cannot_claim_unaffected_without_supported_coverage():
    fixture = AnalyzerFixture(
        conclusion="unaffected", supported=False, files_considered=0
    )

    with pytest.raises(ValueError, match="unaffected requires supported"):
        FixtureAnalyzer().assess(fixture)


@pytest.mark.parametrize(
    ("scenario", "status", "failure_kind"),
    [
        ("pass", "passed", None),
        ("test_failure", "failed", "test_failure"),
        ("timeout", "timed_out", "timeout"),
        ("policy_violation", "blocked", "policy_violation"),
        ("infrastructure_failure", "infrastructure_error", "infrastructure_failure"),
    ],
)
def test_sandbox_fake_keeps_failure_classes_distinct(scenario, status, failure_kind):
    request = SandboxRequest(
        patch_sha256="a" * 64,
        commands=["pytest"],
        scenario=scenario,
    )

    result = FakeSandboxExecutor().execute(request)

    assert result.status == status
    assert result.failure_kind == failure_kind


def test_publisher_is_idempotent_and_preserves_exact_patch():
    patch = "diff --git a/client.py b/client.py\n+new behavior\n"
    request = PublicationRequest(
        migration_id="migration-1",
        attempt_id="attempt-1",
        idempotency_key="publish-123",
        patch=patch,
        patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
    )
    publisher = FakePublisher()

    first = publisher.publish(request)
    second = publisher.publish(request)

    assert first == second
    assert first["patch"] == patch


def test_publisher_rejects_changed_request_for_same_key():
    publisher = FakePublisher()
    patch = "first patch"
    publisher.publish(
        PublicationRequest(
            migration_id="migration-1",
            attempt_id="attempt-1",
            idempotency_key="publish-123",
            patch=patch,
            patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
        )
    )
    changed = "changed patch"

    with pytest.raises(IdempotencyConflictError):
        publisher.publish(
            PublicationRequest(
                migration_id="migration-1",
                attempt_id="attempt-1",
                idempotency_key="publish-123",
                patch=changed,
                patch_sha256=hashlib.sha256(changed.encode()).hexdigest(),
            )
        )


def test_redaction_removes_tokens_and_configured_secrets_from_nested_evidence():
    secret = "customer-super-secret"
    value = {
        "log": f"API_KEY={secret} Authorization: Bearer bearer-value",
        "prompt": ["github_pat_1234567890", "ghp_abcdefghijklmnopqrstuvwxyz"],
    }

    redacted = json.dumps(redact_data(value, [secret]))

    assert secret not in redacted
    assert "bearer-value" not in redacted
    assert "github_pat_" not in redacted
    assert "ghp_" not in redacted
    assert redacted.count("[REDACTED]") == 4
