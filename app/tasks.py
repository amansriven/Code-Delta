import json
import logging
import shutil
import traceback

from app.db import get_connection
from app.engine import DEMO_DIR, compare
from app.procrastinate_app import procrastinate_app
from app.repo_fetch import fetch_ref

logger = logging.getLogger(__name__)


def _get_run(run_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT clone_url, base_ref, head_ref, head_sha, installation_id, repo FROM runs WHERE id = %s",
            (run_id,),
        ).fetchone()
    keys = ["clone_url", "base_ref", "head_ref", "head_sha", "installation_id", "repo"]
    return dict(zip(keys, row))


def _set_status(
    run_id: int, status: str, result: dict | None = None, error: str | None = None
) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE runs SET status = %s, result = %s, error = %s, updated_at = now() WHERE id = %s",
            (status, json.dumps(result) if result is not None else None, error, run_id),
        )


def _run_comparison(run_id: int) -> None:
    run = _get_run(run_id)

    if run["clone_url"] and run["base_ref"] and run["head_ref"]:
        base_dir = fetch_ref(run["clone_url"], run["base_ref"])
        head_dir = fetch_ref(run["clone_url"], run["head_ref"])
        try:
            findings = compare(base_dir, head_dir)
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)
            shutil.rmtree(head_dir, ignore_errors=True)

        if run["installation_id"]:
            try:
                from app.github_client import post_check_run

                post_check_run(run["installation_id"], run["repo"], run["head_sha"], findings)
            except Exception:
                logger.exception("failed to post check run for run_id=%s", run_id)
    else:
        findings = compare(DEMO_DIR / "base", DEMO_DIR / "buggy")

    _set_status(run_id, "done", result={"findings": findings})


@procrastinate_app.task(name="run_comparison")
def run_comparison(run_id: int) -> None:
    """Phase 3: if the run has real repo info (set by the GitHub webhook),
    clone the actual base/PR branches and compare those. Otherwise (e.g. a
    run created directly via POST /runs for local testing) fall back to the
    demo apps, same as Phase 1/2.

    Any failure lands the run in a terminal "failed" state with the error
    recorded, rather than leaving it stuck in "running" forever (what used
    to happen before this — a run whose worker process died mid-task had no
    way to ever reach a terminal status).
    """
    _set_status(run_id, "running")
    try:
        _run_comparison(run_id)
    except Exception:
        logger.exception("run_comparison failed for run_id=%s", run_id)
        _set_status(run_id, "failed", error=traceback.format_exc())
