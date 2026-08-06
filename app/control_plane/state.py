"""Optimistic, explicit lifecycle transitions for Phase 1 entities."""

from collections.abc import Mapping


class StateTransitionError(ValueError):
    pass


class VersionConflictError(ValueError):
    pass


CHANGE_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "detected": frozenset({"normalizing"}),
    "normalizing": frozenset({"ready", "needs_review", "invalid"}),
    "needs_review": frozenset({"ready", "invalid"}),
    "ready": frozenset({"superseded", "withdrawn"}),
    "invalid": frozenset(),
    "withdrawn": frozenset(),
    "superseded": frozenset(),
}

IMPACT_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "queued": frozenset({"analyzing"}),
    "analyzing": frozenset({"affected", "unaffected", "uncertain", "unsupported", "failed"}),
    "affected": frozenset(),
    "unaffected": frozenset(),
    "uncertain": frozenset({"queued"}),
    "unsupported": frozenset(),
    "failed": frozenset({"queued"}),
}

MIGRATION_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "queued": frozenset({"planning"}),
    "planning": frozenset({"generating", "blocked"}),
    "generating": frozenset({"verifying", "needs_revision", "blocked"}),
    "verifying": frozenset({"ready", "needs_revision", "blocked"}),
    "ready": frozenset({"pr_opening", "needs_revision", "snoozed", "declined"}),
    "needs_revision": frozenset({"planning"}),
    "blocked": frozenset({"planning", "pr_opening"}),
    "pr_opening": frozenset({"pr_opened", "blocked"}),
    "pr_opened": frozenset({"approved", "needs_revision", "snoozed", "declined"}),
    "snoozed": frozenset({"queued"}),
    "declined": frozenset({"queued"}),
    "approved": frozenset({"completed"}),
    "completed": frozenset(),
}

ATTEMPT_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "created": frozenset({"planning", "cancelled"}),
    "planning": frozenset({"generating", "failed", "cancelled"}),
    "generating": frozenset({"verifying", "failed", "cancelled"}),
    "verifying": frozenset({"reviewing", "failed", "cancelled"}),
    "reviewing": frozenset({"completed", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def validate_transition(
    transitions: Mapping[str, frozenset[str]],
    current: str,
    requested: str,
    *,
    version: int,
    expected_version: int,
) -> int:
    """Validate an optimistic transition and return the next entity version."""
    if version != expected_version:
        raise VersionConflictError(f"expected version {expected_version}, found {version}")
    if current not in transitions:
        raise StateTransitionError(f"unknown state: {current}")
    if requested not in transitions[current]:
        raise StateTransitionError(f"cannot transition from {current} to {requested}")
    return version + 1
