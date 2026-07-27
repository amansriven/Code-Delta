import time

from app.db import get_connection
from app.procrastinate_app import procrastinate_app


def _set_status(run_id: int, status: str, result: dict | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE runs SET status = %s, result = %s, updated_at = now() WHERE id = %s",
            (status, __import__("json").dumps(result) if result is not None else None, run_id),
        )


@procrastinate_app.task(name="run_comparison")
def run_comparison(run_id: int) -> None:
    """Placeholder for the base-vs-PR comparison engine (Phase 1 of the spec).

    Wires up the job lifecycle now so the queue/dashboard plumbing is real;
    swap the body for the actual comparison engine once it exists.
    """
    _set_status(run_id, "running")
    time.sleep(2)
    _set_status(run_id, "done", result={"regressions": [], "note": "placeholder run"})
