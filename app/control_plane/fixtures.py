"""Fixture adapters proving the core contract is source-format neutral."""

from typing import Any, Protocol

from app.control_plane.models import NormalizedChange


class FixtureAdapter(Protocol):
    adapter_id: str
    adapter_version: str

    def normalize(self, raw: dict[str, Any]) -> NormalizedChange: ...


def _artifact(raw: dict[str, Any], source_type: str) -> dict[str, Any]:
    return {
        "id": raw["artifact_id"],
        "source_type": source_type,
        "canonical_url": raw["canonical_url"],
        "captured_at": raw["captured_at"],
        "sha256": raw["sha256"],
        "media_type": raw.get("media_type"),
        "authoritative": True,
    }


class OpenAPIFixtureAdapter:
    adapter_id = "fixture.openapi"
    adapter_version = "1.0.0"

    def normalize(self, raw: dict[str, Any]) -> NormalizedChange:
        field = raw["required_field_added"]
        artifact = _artifact(raw, "openapi")
        return NormalizedChange.model_validate(
            {
                "id": raw["id"],
                "dedupe_key": f"{raw['provider']['id']}:{raw['operation']}:{raw['path']}:{field}",
                "provider": raw["provider"],
                "status": "ready",
                "detected_at": raw["captured_at"],
                "published_at": raw.get("published_at"),
                "change_type": "request_field_required",
                "severity": "high",
                "breaking": True,
                "summary": f"{raw['operation']} {raw['path']} now requires {field}.",
                "before": {"required": raw["previous_required"]},
                "after": {"required": raw["current_required"]},
                "source_artifacts": [artifact],
                "targets": [
                    {
                        "kind": "endpoint",
                        "name": raw["path"],
                        "operation": raw["operation"],
                    },
                    {"kind": "field", "name": field, "operation": raw["operation"]},
                ],
                "claims": [
                    {
                        "id": f"claim:{field}:required",
                        "summary": f"The captured OpenAPI document requires {field}.",
                        "provenance": "deterministic",
                        "source_artifact_ids": [artifact["id"]],
                        "locator": raw.get("json_pointer"),
                    }
                ],
                "confidence": {
                    "score": 1,
                    "basis": "deterministic",
                    "reasons": ["The required-field set changed in the OpenAPI document."],
                    "unresolved": [],
                },
                "normalizer": {"id": self.adapter_id, "version": self.adapter_version},
            }
        )


class SDKReleaseFixtureAdapter:
    adapter_id = "fixture.sdk-release"
    adapter_version = "1.0.0"

    def normalize(self, raw: dict[str, Any]) -> NormalizedChange:
        artifact = _artifact(raw, "sdk_release")
        removed = raw["removed_symbol"]
        return NormalizedChange.model_validate(
            {
                "id": raw["id"],
                "dedupe_key": (
                    f"{raw['provider']['id']}:{raw['package']}:{raw['version']}:{removed}"
                ),
                "provider": raw["provider"],
                "status": "ready",
                "detected_at": raw["captured_at"],
                "published_at": raw.get("published_at"),
                "change_type": "sdk_symbol_removed",
                "severity": raw.get("severity", "medium"),
                "breaking": True,
                "summary": raw["summary"],
                "version_scope": {
                    "previous": raw.get("previous_version"),
                    "current": raw["version"],
                    "scheme": "semver",
                },
                "source_artifacts": [artifact],
                "targets": [
                    {
                        "kind": "symbol",
                        "name": removed,
                        "package": raw["package"],
                        "ecosystem": raw["ecosystem"],
                        "language": raw["language"],
                    }
                ],
                "migration_guidance": [
                    {
                        "summary": raw["replacement_guidance"],
                        "provenance": "provider_stated",
                        "source_artifact_ids": [artifact["id"]],
                    }
                ],
                "claims": [
                    {
                        "id": f"claim:{removed}:removed",
                        "summary": raw["summary"],
                        "provenance": "provider_stated",
                        "source_artifact_ids": [artifact["id"]],
                        "locator": raw.get("section"),
                    }
                ],
                "confidence": {
                    "score": 0.9,
                    "basis": "inferred",
                    "reasons": ["The official SDK release notes identify the removed symbol."],
                    "unresolved": ["The release-note fixture has no machine-readable symbol diff."],
                },
                "normalizer": {"id": self.adapter_id, "version": self.adapter_version},
            }
        )
