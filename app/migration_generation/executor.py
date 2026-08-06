"""Cloudflare Sandbox executor client with an explicit enablement gate."""

import json
from urllib.parse import urlparse

import httpx

from .models import SandboxExecutionRequest, SandboxExecutionResult

MAX_EXECUTOR_RESPONSE_BYTES = 2_000_000


class SandboxUnavailable(RuntimeError):
    code = "sandbox_unavailable"


class CloudflareSandboxExecutor:
    executor_id = "cloudflare-sandbox"
    executor_version = "0.12.4"

    def __init__(
        self,
        base_url: str,
        bearer_token: str,
        *,
        enabled: bool,
        client: httpx.Client | None = None,
    ) -> None:
        if not enabled:
            raise SandboxUnavailable("sandbox execution is disabled by policy")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("sandbox executor must use credential-free HTTPS")
        if not bearer_token:
            raise ValueError("sandbox executor token is required")
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self.client = client or httpx.Client(timeout=httpx.Timeout(180, connect=5))

    def execute(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        with self.client.stream(
            "POST",
            f"{self.base_url}/v1/execute",
            headers={"Authorization": f"Bearer {self.bearer_token}"},
            json=request.model_dump(mode="json"),
        ) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_EXECUTOR_RESPONSE_BYTES:
                    raise SandboxUnavailable("sandbox response exceeds limit")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise SandboxUnavailable("sandbox returned invalid JSON") from exc
        result = SandboxExecutionResult.model_validate(payload)
        if result.attempt_id != request.attempt_id:
            raise SandboxUnavailable("sandbox response attempt does not match request")
        if result.executor.id != self.executor_id:
            raise SandboxUnavailable("sandbox response executor identity is invalid")
        requested_checks = [(check.id, check.kind) for check in request.checks]
        returned_checks = [(check.id, check.kind) for check in result.checks]
        if returned_checks != requested_checks:
            raise SandboxUnavailable("sandbox response checks do not match request")
        if result.status == "passed" and (
            not result.destroyed or any(check.status != "passed" for check in result.checks)
        ):
            raise SandboxUnavailable("sandbox returned an inconsistent success result")
        return result


class StaticSandboxExecutor:
    def __init__(self, result: SandboxExecutionResult):
        self.result = result

    def execute(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        if request.attempt_id != self.result.attempt_id:
            raise ValueError("sandbox fixture attempt does not match request")
        return self.result.model_copy(deep=True)
