"""Deterministic Phase 1 fakes for later-phase contract consumers.

These components do not execute code or publish externally. They make failure
semantics, idempotency, exact-patch handling, and redaction testable before a
production analyzer, sandbox, or publisher is selected.
"""

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import Field

from app.control_plane.models import ContractModel
from app.control_plane.store import IdempotencyConflictError


class AnalyzerFixture(ContractModel):
    conclusion: Literal["affected", "unaffected", "uncertain", "unsupported"]
    supported: bool
    files_considered: int = Field(ge=0)
    findings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FixtureAnalyzer:
    analyzer_id = "fixture.analyzer"
    analyzer_version = "1.0.0"

    def assess(self, fixture: AnalyzerFixture) -> dict[str, Any]:
        if fixture.conclusion == "unaffected" and not fixture.supported:
            raise ValueError("unaffected requires supported deterministic coverage")
        return {
            "conclusion": fixture.conclusion,
            "findings": fixture.findings,
            "coverage": {
                "supported": fixture.supported,
                "files_considered": fixture.files_considered,
                "limitations": fixture.limitations,
            },
            "analyzer": {"id": self.analyzer_id, "version": self.analyzer_version},
        }


class SandboxRequest(ContractModel):
    patch_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    commands: list[str] = Field(min_length=1)
    scenario: Literal[
        "pass", "test_failure", "timeout", "policy_violation", "infrastructure_failure"
    ]


class SandboxResult(ContractModel):
    status: Literal["passed", "failed", "timed_out", "blocked", "infrastructure_error"]
    failure_kind: str | None = None
    patch_sha256: str
    exit_code: int | None = None
    display_log: str


class FakeSandboxExecutor:
    executor_id = "fixture.sandbox"
    executor_version = "1.0.0"

    def execute(self, request: SandboxRequest) -> SandboxResult:
        outcomes = {
            "pass": ("passed", None, 0, "All configured checks passed."),
            "test_failure": ("failed", "test_failure", 1, "Tests failed."),
            "timeout": ("timed_out", "timeout", None, "Execution timed out."),
            "policy_violation": (
                "blocked",
                "policy_violation",
                None,
                "Command rejected by sandbox policy.",
            ),
            "infrastructure_failure": (
                "infrastructure_error",
                "infrastructure_failure",
                None,
                "Sandbox infrastructure was unavailable.",
            ),
        }
        status, failure_kind, exit_code, display_log = outcomes[request.scenario]
        return SandboxResult(
            status=status,
            failure_kind=failure_kind,
            patch_sha256=request.patch_sha256,
            exit_code=exit_code,
            display_log=display_log,
        )


class PublicationRequest(ContractModel):
    migration_id: str
    attempt_id: str
    idempotency_key: str = Field(min_length=8)
    patch: str
    patch_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class FakePublisher:
    """Record exact patch bytes and reject unsafe idempotency-key reuse."""

    def __init__(self) -> None:
        self.publications: dict[str, dict[str, str]] = {}

    def publish(self, request: PublicationRequest) -> dict[str, str]:
        actual_digest = hashlib.sha256(request.patch.encode()).hexdigest()
        if actual_digest != request.patch_sha256.lower():
            raise ValueError("patch digest does not match exact patch content")
        fingerprint = hashlib.sha256(
            json.dumps(request.model_dump(), sort_keys=True).encode()
        ).hexdigest()
        prior = self.publications.get(request.idempotency_key)
        if prior:
            if prior["fingerprint"] != fingerprint:
                raise IdempotencyConflictError(
                    "idempotency key was already used with another publication"
                )
            return prior
        result = {
            "migration_id": request.migration_id,
            "attempt_id": request.attempt_id,
            "patch_sha256": actual_digest,
            "patch": request.patch,
            "fingerprint": fingerprint,
        }
        self.publications[request.idempotency_key] = result
        return result


TOKEN_PATTERNS = (
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]+"),
    re.compile(r"(?i)Bearer\s+[^\s,;]+"),
)


def redact_text(value: str, secrets: list[str]) -> str:
    redacted = value
    for secret in sorted({item for item in secrets if item}, key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    for pattern in TOKEN_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_data(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, list):
        return [redact_data(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_data(item, secrets) for item in value)
    if isinstance(value, dict):
        return {key: redact_data(item, secrets) for key, item in value.items()}
    return value
