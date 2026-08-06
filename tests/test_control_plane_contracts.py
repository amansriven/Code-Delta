import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.control_plane.fixtures import OpenAPIFixtureAdapter, SDKReleaseFixtureAdapter
from app.control_plane.models import MigrationEvidence, NormalizedChange, OrchestrationJob
from app.control_plane.state import (
    ATTEMPT_TRANSITIONS,
    CHANGE_TRANSITIONS,
    MIGRATION_TRANSITIONS,
    StateTransitionError,
    VersionConflictError,
    validate_transition,
)
from app.control_plane.store import _decode_cursor, _encode_cursor

FIXTURES = Path(__file__).parent / "fixtures" / "providers"
ARCHITECTURE_EXAMPLES = Path(__file__).parent.parent / "docs" / "architecture" / "examples"


@pytest.mark.parametrize(
    ("adapter", "fixture", "change_type"),
    [
        (OpenAPIFixtureAdapter(), "openapi-change.json", "request_field_required"),
        (SDKReleaseFixtureAdapter(), "sdk-release.json", "sdk_symbol_removed"),
    ],
)
def test_structurally_different_adapters_share_contract(adapter, fixture, change_type):
    raw = json.loads((FIXTURES / fixture).read_text())
    change = adapter.normalize(raw)

    assert isinstance(change, NormalizedChange)
    assert change.schema_version == "1.0"
    assert change.change_type == change_type
    assert change.source_artifacts[0].authoritative is True


def test_change_contract_rejects_claim_for_unknown_artifact():
    raw = json.loads((FIXTURES / "openapi-change.json").read_text())
    payload = OpenAPIFixtureAdapter().normalize(raw).model_dump(mode="json")
    payload["claims"][0]["source_artifact_ids"] = ["missing"]

    with pytest.raises(ValidationError, match="unknown source artifacts"):
        NormalizedChange.model_validate(payload)


def test_normalized_change_example_satisfies_pydantic_contract():
    payload = json.loads((ARCHITECTURE_EXAMPLES / "normalized-change.example.json").read_text())

    change = NormalizedChange.model_validate(payload)

    assert change.schema_version == "1.0"
    assert change.provider.id == "examplepay"


def test_migration_evidence_example_satisfies_pydantic_contract():
    payload = json.loads((ARCHITECTURE_EXAMPLES / "migration-evidence.example.json").read_text())

    evidence = MigrationEvidence.model_validate(payload)

    assert evidence.schema_version == "1.0"
    assert evidence.impact.conclusion == "affected"
    assert all(check.deterministic for check in evidence.verification_checks)


def test_orchestration_envelope_is_versioned_and_serializable():
    job = OrchestrationJob(
        workspace_id="workspace-1",
        entity_type="migration",
        entity_id="migration-1",
        expected_state="queued",
        expected_version=1,
        requested_state="planning",
        implementation_version="phase1.0",
        idempotency_key="migration-1:planning",
        attempt_number=1,
        trace_id="trace-1",
        causation_id="change-1",
    )

    assert job.model_dump(mode="json")["contract_version"] == "1.0"


@pytest.mark.parametrize(
    ("machine", "current", "requested"),
    [
        (CHANGE_TRANSITIONS, "detected", "normalizing"),
        (MIGRATION_TRANSITIONS, "queued", "planning"),
        (ATTEMPT_TRANSITIONS, "reviewing", "completed"),
    ],
)
def test_valid_transition_increments_version(machine, current, requested):
    assert validate_transition(machine, current, requested, version=3, expected_version=3) == 4


def test_transition_rejects_stale_version():
    with pytest.raises(VersionConflictError, match="expected version 2, found 3"):
        validate_transition(
            MIGRATION_TRANSITIONS, "queued", "planning", version=3, expected_version=2
        )


def test_transition_rejects_invalid_lifecycle_jump():
    with pytest.raises(StateTransitionError, match="cannot transition"):
        validate_transition(
            MIGRATION_TRANSITIONS, "queued", "approved", version=1, expected_version=1
        )


def test_pagination_cursor_is_opaque_and_rejects_malformed_values():
    from datetime import UTC, datetime

    position = (datetime(2026, 8, 5, tzinfo=UTC), "change-1")

    assert _decode_cursor(_encode_cursor(*position)) == position
    with pytest.raises(ValueError, match="invalid cursor"):
        _decode_cursor("not-valid-base64%%%")
