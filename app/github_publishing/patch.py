"""Reconstruct the exact validated Phase 4 patch artifact."""

import hashlib
import json

from app.ingestion.storage import ArtifactStore
from app.migration_generation.policy import normalize_repository_path

from .models import PublicationEdit


class PublicationPolicyError(ValueError):
    code = "publication_policy_violation"


def load_publication_edits(
    artifact_store: ArtifactStore,
    object_ref: str,
    expected_sha256: str,
) -> list[PublicationEdit]:
    content = artifact_store.read(object_ref)
    if len(content) > 2_000_000:
        raise PublicationPolicyError("patch artifact exceeds publication limit")
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise PublicationPolicyError("patch artifact digest does not match evidence")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise PublicationPolicyError("patch artifact is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "edits"}:
        raise PublicationPolicyError("patch artifact has an invalid envelope")
    if payload["schema_version"] != "1.0" or not isinstance(payload["edits"], list):
        raise PublicationPolicyError("patch artifact has an unsupported schema")
    if not 1 <= len(payload["edits"]) <= 100:
        raise PublicationPolicyError("patch artifact has an invalid edit count")
    edits = [PublicationEdit.model_validate(item) for item in payload["edits"]]
    paths = [normalize_repository_path(edit.path) for edit in edits]
    if len(paths) != len(set(paths)):
        raise PublicationPolicyError("patch artifact contains duplicate paths")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if canonical != content:
        raise PublicationPolicyError("patch artifact is not canonical")
    return edits
