from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.db import get_connection, init_schema
from app.procrastinate_app import procrastinate_app
from app.tasks import run_comparison

app = FastAPI(title="CodeDelta")


@app.on_event("startup")
def startup() -> None:
    init_schema()
    procrastinate_app.open()


@app.on_event("shutdown")
def shutdown() -> None:
    procrastinate_app.close()


class CreateRunRequest(BaseModel):
    repo: str
    pr_number: int | None = None


@app.post("/runs")
def create_run(req: CreateRunRequest):
    with get_connection() as conn:
        row = conn.execute(
            "INSERT INTO runs (repo, pr_number) VALUES (%s, %s) RETURNING id",
            (req.repo, req.pr_number),
        ).fetchone()
        run_id = row[0]

    run_comparison.defer(run_id=run_id)
    return {"id": run_id, "status": "pending"}


@app.get("/runs/{run_id}")
def get_run(run_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, repo, pr_number, status, result, created_at, updated_at FROM runs WHERE id = %s",
            (run_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    keys = ["id", "repo", "pr_number", "status", "result", "created_at", "updated_at"]
    return dict(zip(keys, row))


@app.get("/runs")
def list_runs():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, repo, pr_number, status, created_at FROM runs ORDER BY id DESC LIMIT 50"
        ).fetchall()
    keys = ["id", "repo", "pr_number", "status", "created_at"]
    return [dict(zip(keys, r)) for r in rows]
