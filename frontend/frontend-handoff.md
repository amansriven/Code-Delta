# Delta Code — Frontend/Dashboard Handoff

> **Status:** Current verifier API reference. It does not define the future
> migration-inbox API. The accepted product direction and new contracts are in
> the [Phase 0 product RFC](../docs/architecture/phase-0-rfc.md).

Backend context for the dashboard currently deployed with Delta Code. This
document describes the existing `/runs` surface and data shapes only.

## What the current verifier does

Delta Code runs generated edge-case HTTP requests against a PR's base and
head branches of a FastAPI app, and reports only requests that behaved
*differently* between the two — actual evidence of a regression, not an
LLM's opinion. A GitHub App webhook triggers a "run" per PR; the run's
result is a list of "findings."

## Running the backend locally

```bash
docker compose up -d   # Postgres
./.venv/bin/pip install -r requirements.txt
PYTHONPATH=. ./.venv/bin/python -m procrastinate --app app.procrastinate_app.procrastinate_app schema --apply
./.venv/bin/uvicorn app.main:app --reload           # API on :8000
PYTHONPATH=. ./.venv/bin/python -m procrastinate --app app.procrastinate_app.procrastinate_app worker  # separate terminal
```

Hosted run endpoints require a secure GitHub-backed session and filter data to
repositories available to that session. Local development still needs the
OAuth and GitHub App environment described in
[`docs/LOCAL_DEVELOPMENT.md`](../docs/LOCAL_DEVELOPMENT.md) for the complete
authenticated flow.

## API endpoints (all in `app/main.py` / `app/webhook.py`)

### `GET /runs`
Returns the 50 most recent runs, newest first. Lightweight — no `result`
payload, just enough for a list view.

```json
[
  {"id": 14, "repo": "acme/delta-code-demo-app", "pr_number": 1, "status": "done", "created_at": "2026-07-27T06:51:34.538262+00:00"},
  {"id": 13, "repo": "acme/delta-code-demo-app", "pr_number": 1, "status": "done", "created_at": "2026-07-27T06:49:18.073678+00:00"}
]
```

### `GET /runs/{id}`
Full run detail including findings. Real example, from an actual PR run
(not a demo/placeholder):

```json
{
  "id": 14,
  "repo": "acme/delta-code-demo-app",
  "pr_number": 1,
  "status": "done",
  "result": {
    "findings": [
      {
        "case": "omit_discount",
        "kind": "regression",
        "request": {
          "method": "POST",
          "path": "/items",
          "json": {"name": "example", "price": 1.0}
        },
        "base_response": {
          "status_code": 201,
          "body": {"name": "example", "price": 1.0, "discount": 0.0}
        },
        "pr_response": {
          "status_code": 422,
          "body": {"detail": [{"loc": ["body", "discount"], "msg": "Field required", "type": "missing", "input": {"name": "example", "price": 1.0}}]}
        }
      }
    ]
  },
  "created_at": "2026-07-27T06:51:34.538262+00:00",
  "updated_at": "2026-07-27T06:51:37.338318+00:00"
}
```

`result` is `null` while `status` is `pending`/`running`.

### `POST /runs`
`{"repo": str, "pr_number": int}` — creates a run manually (used for local
testing without a real GitHub PR; falls back to comparing the bundled demo
apps rather than a real repo). Not something the dashboard needs to call
under normal use — runs are created by the GitHub webhook.

### `POST /webhooks/github`
GitHub webhook receiver. Not a dashboard concern, but explains where rows
in `runs` come from.

## Fields to know about but that don't have a "nice" getter yet

The `runs` table (see `app/db.py`) also has `clone_url`, `base_ref`,
`base_sha`, `head_ref`, `head_sha`, `installation_id` — populated for
webhook-triggered runs, `null` for manually-created ones. None of these are
currently returned by `GET /runs/{id}` or `GET /runs` — if the dashboard
wants to show e.g. the head commit SHA or link back to the PR on GitHub,
those endpoints need small additions first (trivial — just add columns to
the SELECT).

## `status` lifecycle

`pending` → `running` → `done` (set by `app/tasks.py`). No `failed` state
currently exists — if the comparison engine throws, the task raises and the
row is left stuck in whatever status it last had. Worth asking the backend
to add a `failed` status + error message before the dashboard needs to
handle that case gracefully.

## `finding.kind` — the two categories to design for

- `"regression"` — base branch succeeded (2xx), PR branch failed. This is
  the headline case; should probably read as more severe.
- `"status_code_changed"` — status code differs some other way (e.g. a
  silent `404 -> 200`, or a request that used to correctly fail now silently
  succeeds). Real, worth surfacing, but not the same severity as a
  regression — the spec's framing is "worth a note," not "you broke this."

The implemented run-detail UI distinguishes these finding types. Preserve the
semantic difference while the verifier remains available as a migration
verification capability.

## Historical first cut

1. Runs list (`GET /runs`) — repo, PR number, status, timestamp, link to
   the GitHub PR (needs `pr_number` + `repo` to construct
   `https://github.com/{repo}/pull/{pr_number}`; no stored URL currently)
2. Run detail (`GET /runs/{id}`) — one card/row per finding, each showing
   the request (method/path/body), and a base-vs-PR response diff
   (status code + body side by side), with `kind` visually distinguished
3. The first cut originally omitted authentication and richer run state. Those
   capabilities now exist; cursor pagination and live push updates remain
   future work.
