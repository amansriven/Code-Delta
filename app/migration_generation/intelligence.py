"""Schema-validated migration intelligence gateway boundary."""

import json
from typing import Protocol
from urllib.parse import urlparse

import httpx

from app.control_plane.models import (
    AttemptReview,
    MigrationPlan,
    PatchEvidence,
    Recommendation,
)

from .models import GenerationProposal, PlanningContext, SandboxExecutionResult

MAX_GATEWAY_RESPONSE_BYTES = 5_000_000


class IntelligenceUnavailable(RuntimeError):
    code = "migration_intelligence_unavailable"


class ReviewProposal(Protocol):
    review: AttemptReview
    recommendation: Recommendation


class MigrationIntelligence(Protocol):
    def propose(self, context: PlanningContext) -> GenerationProposal: ...

    def review(
        self,
        context: PlanningContext,
        plan: MigrationPlan,
        patch: PatchEvidence,
        execution: SandboxExecutionResult,
    ) -> tuple[AttemptReview, Recommendation]: ...


class StaticMigrationIntelligence:
    """Deterministic fixture gateway used by tests and controlled evaluations."""

    def __init__(
        self,
        proposal: GenerationProposal,
        review: AttemptReview,
        recommendation: Recommendation,
    ) -> None:
        self.proposal = proposal
        self.review_result = review
        self.recommendation = recommendation

    def propose(self, context: PlanningContext) -> GenerationProposal:
        del context
        return self.proposal.model_copy(deep=True)

    def review(
        self,
        context: PlanningContext,
        plan: MigrationPlan,
        patch: PatchEvidence,
        execution: SandboxExecutionResult,
    ) -> tuple[AttemptReview, Recommendation]:
        del context, plan, patch, execution
        return self.review_result.model_copy(deep=True), self.recommendation.model_copy(deep=True)


class HttpMigrationIntelligence:
    """Calls a dedicated model gateway; model credentials never enter this process."""

    def __init__(self, base_url: str, bearer_token: str, client: httpx.Client | None = None):
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("migration intelligence gateway must use credential-free HTTPS")
        if not bearer_token:
            raise ValueError("migration intelligence gateway token is required")
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self.client = client or httpx.Client(timeout=httpx.Timeout(120, connect=5))

    def _post(self, path: str, payload: dict) -> dict:
        with self.client.stream(
            "POST",
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.bearer_token}"},
            json=payload,
        ) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_GATEWAY_RESPONSE_BYTES:
                    raise IntelligenceUnavailable("migration intelligence response exceeds limit")
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise IntelligenceUnavailable("migration intelligence returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise IntelligenceUnavailable("migration intelligence returned invalid contract")
        return value

    def propose(self, context: PlanningContext) -> GenerationProposal:
        payload = self._post("/v1/migrations/propose", context.model_dump(mode="json"))
        return GenerationProposal.model_validate(payload)

    def review(
        self,
        context: PlanningContext,
        plan: MigrationPlan,
        patch: PatchEvidence,
        execution: SandboxExecutionResult,
    ) -> tuple[AttemptReview, Recommendation]:
        payload = self._post(
            "/v1/migrations/review",
            {
                "context": context.model_dump(mode="json"),
                "plan": plan.model_dump(mode="json"),
                "patch": patch.model_dump(mode="json"),
                "execution": execution.model_dump(mode="json"),
            },
        )
        return (
            AttemptReview.model_validate(payload.get("review")),
            Recommendation.model_validate(payload.get("recommendation")),
        )
