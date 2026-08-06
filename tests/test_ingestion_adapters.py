import hashlib
import json
from datetime import UTC, datetime

from app.ingestion.adapters import OpenAPIAdapter, StructuredReleaseAdapter
from app.ingestion.models import CapturedArtifact, ProviderSource


def source(source_type="openapi", adapter_id="openapi.diff"):
    return ProviderSource(
        id="source-1",
        workspace_id="workspace-1",
        provider={"id": "example", "name": "Example"},
        source_type=source_type,
        canonical_url="https://api.example.com/source.json",
        official_domains=["example.com"],
        adapter_id=adapter_id,
    )


def artifact(identifier, content, *, minute=0):
    digest = hashlib.sha256(content).hexdigest()
    return CapturedArtifact(
        id=identifier,
        source_id="source-1",
        canonical_url="https://api.example.com/source.json",
        retrieved_url="https://api.example.com/source.json",
        captured_at=datetime(2026, 8, 5, 12, minute, tzinfo=UTC),
        retrieval_status="captured",
        media_type="application/json",
        size_bytes=len(content),
        sha256=digest,
        object_ref=f"sha256/{digest[:2]}/{digest}",
        collector_id="test",
        collector_version="1.0",
    )


def test_openapi_adapter_baselines_first_capture_without_false_changes():
    content = json.dumps({"openapi": "3.1.0", "paths": {"/items": {"get": {}}}}).encode()

    changes = OpenAPIAdapter().normalize(source(), None, (artifact("current", content), content))

    assert changes == []


def test_openapi_adapter_detects_endpoint_and_required_field_changes():
    before = json.dumps(
        {
            "paths": {
                "/charges": {
                    "post": {
                        "requestBody": {
                            "content": {"application/json": {"schema": {"required": ["amount"]}}}
                        }
                    }
                },
                "/legacy": {"get": {}},
            }
        }
    ).encode()
    after = json.dumps(
        {
            "paths": {
                "/charges": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"required": ["amount", "payment_method"]}
                                }
                            }
                        }
                    }
                },
                "/new": {"get": {}},
            }
        }
    ).encode()

    changes = OpenAPIAdapter().normalize(
        source(),
        (artifact("before", before), before),
        (artifact("after", after, minute=1), after),
    )

    assert {change.change_type for change in changes} == {
        "endpoint_added",
        "endpoint_removed",
        "request_field_required",
    }
    assert all(len(change.source_artifacts) == 2 for change in changes)
    assert all(change.confidence.basis == "deterministic" for change in changes)


def test_structured_release_preserves_provider_stated_provenance_and_stable_dedupe():
    document = {
        "changes": [
            {
                "key": "sdk-v5-send-removed",
                "change_type": "sdk_symbol_removed",
                "severity": "high",
                "breaking": True,
                "summary": "Client.send was removed.",
                "targets": [
                    {
                        "kind": "symbol",
                        "name": "Client.send",
                        "package": "example-sdk",
                        "ecosystem": "pypi",
                        "language": "python",
                    }
                ],
                "migration_guidance": "Use Client.messages.send.",
            }
        ]
    }
    content = json.dumps(document).encode()
    configured = source("structured_release", "structured-release.v1")

    change = StructuredReleaseAdapter().normalize(
        configured, None, (artifact("release", content), content)
    )[0]

    assert change.dedupe_key == "example:sdk-v5-send-removed"
    assert change.claims[0].provenance == "provider_stated"
    assert change.confidence.unresolved
