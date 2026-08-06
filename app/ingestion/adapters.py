"""Provider-independent adapters for initial Phase 2 source formats."""

import hashlib
import json
from typing import Any, Protocol

from pydantic import Field

from app.control_plane.models import ContractModel, NormalizedChange
from app.ingestion.models import CapturedArtifact, ProviderSource
from app.ingestion.security import SourcePolicyError, enforce_json_depth


class AdapterError(ValueError):
    pass


class AdapterCapabilities(ContractModel):
    adapter_id: str
    adapter_version: str
    source_types: list[str] = Field(min_length=1)
    deterministic_change_types: list[str]
    provider_stated_change_types: list[str] = Field(default_factory=list)
    inferred_change_types: list[str] = Field(default_factory=list)
    maximum_artifact_bytes: int = Field(ge=1)
    known_blind_spots: list[str] = Field(default_factory=list)


class SourceAdapter(Protocol):
    adapter_id: str
    adapter_version: str

    def capabilities(self) -> AdapterCapabilities: ...
    def normalize(
        self,
        source: ProviderSource,
        previous: tuple[CapturedArtifact, bytes] | None,
        current: tuple[CapturedArtifact, bytes],
    ) -> list[NormalizedChange]: ...


def _load_json(content: bytes) -> Any:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError("source artifact is not valid UTF-8 JSON") from exc
    try:
        enforce_json_depth(document)
    except SourcePolicyError as exc:
        raise AdapterError(str(exc)) from exc
    return document


def _source_artifact(artifact: CapturedArtifact, source_type: str) -> dict[str, Any]:
    schema_source_type = "other" if source_type == "structured_release" else source_type
    return {
        "id": artifact.id,
        "source_type": schema_source_type,
        "canonical_url": str(artifact.canonical_url),
        "captured_at": artifact.captured_at,
        "sha256": artifact.sha256,
        "media_type": artifact.media_type,
        "authoritative": True,
    }


def _stable_id(prefix: str, semantic_key: str) -> str:
    digest = hashlib.sha256(semantic_key.encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _request_required(operation: dict[str, Any]) -> set[str]:
    content = operation.get("requestBody", {}).get("content", {})
    schema = content.get("application/json", {}).get("schema", {})
    required = schema.get("required", [])
    return {item for item in required if isinstance(item, str)}


class OpenAPIAdapter:
    adapter_id = "openapi.diff"
    adapter_version = "1.0.0"

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            source_types=["openapi"],
            deterministic_change_types=[
                "endpoint_added", "endpoint_removed", "request_field_required"
            ],
            maximum_artifact_bytes=5_000_000,
            known_blind_spots=[
                "Only JSON OpenAPI documents are supported.",
                "Referenced request schemas are not dereferenced in Phase 2.",
            ],
        )

    def normalize(
        self,
        source: ProviderSource,
        previous: tuple[CapturedArtifact, bytes] | None,
        current: tuple[CapturedArtifact, bytes],
    ) -> list[NormalizedChange]:
        if previous is None:
            return []
        previous_artifact, previous_content = previous
        current_artifact, current_content = current
        before = _load_json(previous_content)
        after = _load_json(current_content)
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise AdapterError("OpenAPI artifacts must contain JSON objects")
        before_paths = before.get("paths", {})
        after_paths = after.get("paths", {})
        if not isinstance(before_paths, dict) or not isinstance(after_paths, dict):
            raise AdapterError("OpenAPI paths must be objects")

        artifacts = [
            _source_artifact(previous_artifact, "openapi"),
            _source_artifact(current_artifact, "openapi"),
        ]
        changes: list[NormalizedChange] = []
        for path in sorted(set(before_paths) | set(after_paths)):
            before_item = before_paths.get(path, {})
            after_item = after_paths.get(path, {})
            for method in ("get", "post", "put", "patch", "delete", "options", "head"):
                had_operation = isinstance(before_item, dict) and method in before_item
                has_operation = isinstance(after_item, dict) and method in after_item
                operation = method.upper()
                semantic = f"{source.provider.id}:{operation}:{path}"
                if had_operation and not has_operation:
                    changes.append(
                        self._change(
                            source,
                            current_artifact,
                            artifacts,
                            semantic=f"{semantic}:removed",
                            change_type="endpoint_removed",
                            severity="high",
                            breaking=True,
                            summary=f"{operation} {path} was removed.",
                            target={"kind": "endpoint", "name": path, "operation": operation},
                            before=before_item[method],
                            after=None,
                        )
                    )
                    continue
                if has_operation and not had_operation:
                    changes.append(
                        self._change(
                            source,
                            current_artifact,
                            artifacts,
                            semantic=f"{semantic}:added",
                            change_type="endpoint_added",
                            severity="informational",
                            breaking=False,
                            summary=f"{operation} {path} was added.",
                            target={"kind": "endpoint", "name": path, "operation": operation},
                            before=None,
                            after=after_item[method],
                        )
                    )
                    continue
                if not had_operation or not has_operation:
                    continue
                previous_required = _request_required(before_item[method])
                current_required = _request_required(after_item[method])
                for field in sorted(current_required - previous_required):
                    changes.append(
                        self._change(
                            source,
                            current_artifact,
                            artifacts,
                            semantic=f"{semantic}:required:{field}",
                            change_type="request_field_required",
                            severity="high",
                            breaking=True,
                            summary=f"{operation} {path} now requires {field}.",
                            target={
                                "kind": "field",
                                "name": field,
                                "operation": f"{operation} {path}",
                            },
                            before={"required": sorted(previous_required)},
                            after={"required": sorted(current_required)},
                        )
                    )
        return changes

    def _change(
        self,
        source: ProviderSource,
        current: CapturedArtifact,
        artifacts: list[dict[str, Any]],
        *,
        semantic: str,
        change_type: str,
        severity: str,
        breaking: bool,
        summary: str,
        target: dict[str, Any],
        before: Any,
        after: Any,
    ) -> NormalizedChange:
        dedupe_key = f"{semantic}:{current.sha256[:16]}"
        change_id = _stable_id("change", dedupe_key)
        return NormalizedChange.model_validate(
            {
                "id": change_id,
                "dedupe_key": dedupe_key,
                "provider": source.provider.model_dump(),
                "status": "ready",
                "detected_at": current.captured_at,
                "change_type": change_type,
                "severity": severity,
                "breaking": breaking,
                "summary": summary,
                "before": before,
                "after": after,
                "source_artifacts": artifacts,
                "targets": [target],
                "claims": [
                    {
                        "id": f"claim:{change_id}",
                        "summary": summary,
                        "provenance": "deterministic",
                        "source_artifact_ids": [artifact["id"] for artifact in artifacts],
                    }
                ],
                "confidence": {
                    "score": 1,
                    "basis": "deterministic",
                    "reasons": ["Produced by a deterministic OpenAPI artifact diff."],
                    "unresolved": [],
                },
                "normalizer": {"id": self.adapter_id, "version": self.adapter_version},
            }
        )


class StructuredReleaseAdapter:
    adapter_id = "structured-release.v1"
    adapter_version = "1.0.0"

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            source_types=["structured_release"],
            deterministic_change_types=[],
            provider_stated_change_types=[
                "sdk_symbol_added", "sdk_symbol_removed", "sdk_symbol_changed", "sdk_release",
                "deprecation", "feature", "security", "unknown"
            ],
            maximum_artifact_bytes=2_000_000,
            known_blind_spots=[
                "Provider-stated entries are not independently verified in Phase 2."
            ],
        )

    def normalize(
        self,
        source: ProviderSource,
        previous: tuple[CapturedArtifact, bytes] | None,
        current: tuple[CapturedArtifact, bytes],
    ) -> list[NormalizedChange]:
        del previous
        artifact, content = current
        document = _load_json(content)
        if not isinstance(document, dict) or not isinstance(document.get("changes"), list):
            raise AdapterError("structured release must contain a changes array")
        artifact_ref = _source_artifact(artifact, "structured_release")
        changes = []
        for entry in document["changes"]:
            if not isinstance(entry, dict):
                raise AdapterError("structured release entries must be objects")
            key = entry.get("key")
            summary = entry.get("summary")
            targets = entry.get("targets")
            if (
                not isinstance(key, str)
                or not isinstance(summary, str)
                or not isinstance(targets, list)
            ):
                raise AdapterError("structured release entry is missing key, summary, or targets")
            change_type = entry.get("change_type", "unknown")
            if change_type not in self.capabilities().provider_stated_change_types:
                raise AdapterError("structured release change type is not supported")
            dedupe_key = f"{source.provider.id}:{key}"
            change_id = _stable_id("change", dedupe_key)
            guidance = entry.get("migration_guidance")
            changes.append(
                NormalizedChange.model_validate(
                    {
                        "id": change_id,
                        "dedupe_key": dedupe_key,
                        "provider": source.provider.model_dump(),
                        "status": "ready",
                        "detected_at": artifact.captured_at,
                        "published_at": entry.get("published_at"),
                        "effective_at": entry.get("effective_at"),
                        "change_type": change_type,
                        "severity": entry.get("severity", "unknown"),
                        "breaking": entry.get("breaking"),
                        "summary": summary,
                        "before": entry.get("before"),
                        "after": entry.get("after"),
                        "source_artifacts": [artifact_ref],
                        "targets": targets,
                        "migration_guidance": (
                            [
                                {
                                    "summary": guidance,
                                    "provenance": "provider_stated",
                                    "source_artifact_ids": [artifact.id],
                                }
                            ]
                            if isinstance(guidance, str) and guidance
                            else []
                        ),
                        "claims": [
                            {
                                "id": f"claim:{change_id}",
                                "summary": summary,
                                "provenance": "provider_stated",
                                "source_artifact_ids": [artifact.id],
                                "locator": entry.get("locator"),
                            }
                        ],
                        "confidence": {
                            "score": 0.9,
                            "basis": "inferred",
                            "reasons": [
                                "The configured official structured feed states this change."
                            ],
                            "unresolved": ["Provider statement was not independently verified."],
                        },
                        "normalizer": {"id": self.adapter_id, "version": self.adapter_version},
                    }
                )
            )
        return changes


DEFAULT_ADAPTERS: dict[str, SourceAdapter] = {
    OpenAPIAdapter.adapter_id: OpenAPIAdapter(),
    StructuredReleaseAdapter.adapter_id: StructuredReleaseAdapter(),
}
