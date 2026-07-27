import hashlib
import hmac
import os

from fastapi import APIRouter, Header, HTTPException, Request

from app.db import get_connection
from app.tasks import run_comparison

router = APIRouter()

HANDLED_ACTIONS = {"opened", "synchronize"}


def _verify_signature(body: bytes, signature: str | None) -> None:
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="GITHUB_WEBHOOK_SECRET not configured")
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="missing signature")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="invalid signature")


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
):
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    if x_github_event != "pull_request":
        return {"ignored": True, "reason": f"event={x_github_event}"}

    payload = await request.json()
    if payload.get("action") not in HANDLED_ACTIONS:
        return {"ignored": True, "reason": f"action={payload.get('action')}"}

    pr = payload["pull_request"]
    repo = payload["repository"]["full_name"]
    installation_id = payload.get("installation", {}).get("id")

    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO runs (repo, pr_number, clone_url, base_ref, base_sha, head_ref, head_sha, installation_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                repo,
                pr["number"],
                pr["base"]["repo"]["clone_url"],
                pr["base"]["ref"],
                pr["base"]["sha"],
                pr["head"]["ref"],
                pr["head"]["sha"],
                installation_id,
            ),
        ).fetchone()
        run_id = row[0]

    run_comparison.defer(run_id=run_id)
    return {"id": run_id, "status": "pending"}
