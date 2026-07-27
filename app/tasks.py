import json

from app.db import get_connection
from app.engine import DEMO_DIR, compare
from app.procrastinate_app import procrastinate_app


def _set_status(run_id: int, status: str, result: dict | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE runs SET status = %s, result = %s, updated_at = now() WHERE id = %s",
            (status, json.dumps(result) if result is not None else None, run_id),
        )


@procrastinate_app.task(name="run_comparison")
def run_comparison(run_id: int) -> None:
    """Phase 1 of the spec: no GitHub integration yet, so every run compares
    the hand-built demo apps (demo_apps/base vs demo_apps/buggy) rather than
    a real PR's branches. Swap in real repo checkouts once Phase 3 lands.
    """
    _set_status(run_id, "running")
    findings = compare(DEMO_DIR / "base", DEMO_DIR / "buggy")
    _set_status(run_id, "done", result={"findings": findings})
