import pytest

from app.ingestion.store import _health_status, mark_sync_status


@pytest.mark.parametrize(
    ("enabled", "failures", "has_success", "status"),
    [
        (False, 0, False, "disabled"),
        (True, 0, False, "never_synced"),
        (True, 0, True, "healthy"),
        (True, 1, True, "degraded"),
        (True, 3, True, "failing"),
    ],
)
def test_source_health_classification(enabled, failures, has_success, status):
    assert _health_status(enabled, failures, has_success) == status


def test_sync_status_rejects_nonterminal_or_unknown_state_before_database_access():
    with pytest.raises(ValueError, match="invalid source sync status"):
        mark_sync_status("workspace", "source", "key", "queued")
