# CodeDelta

See [api-verifier-spec.md](api-verifier-spec.md) for the product spec.

## Job queue

Runs are tracked in a `runs` table in Postgres and processed asynchronously via
[procrastinate](https://procrastinate.readthedocs.io/) (a Postgres-backed task
queue — no Redis/Celery needed). `POST /runs` inserts a row and enqueues a job;
a separate `procrastinate worker` process picks it up and updates the row's
status as it runs. This keeps webhook handlers fast (insert + enqueue, return
immediately) and gives the future dashboard a table to poll/query for status.

`app/tasks.py::run_comparison` compares real PR branches when the run came
from a GitHub webhook (see below), and falls back to the demo apps
(`demo_apps/base` vs `demo_apps/buggy`) for runs created directly via
`POST /runs` — handy for local testing without needing a real PR.

## Comparison engine (Phases 1-2)

- `app/engine.py` — spins up base and PR versions of the target app as real
  subprocesses, runs generated edge-case requests against both, and returns
  only findings where behavior differed (`kind: "regression"` when base
  passed and PR failed; `kind: "status_code_changed"` for any other
  status-code difference, e.g. a silent 404 → 200).
- `app/openapi_diff.py` — generates those edge cases from the diff between
  both apps' `/openapi.json`: body fields that became required or changed
  type, and path/query params, targeted at whatever actually changed rather
  than a fixed list.
- `demo_apps/` — a small FastAPI app in five variants (`base` plus four
  intentionally-bugged versions) used to stress-test the generator.

## GitHub App integration (Phase 3)

`app/webhook.py` receives `pull_request` webhooks, `app/repo_fetch.py` clones
the base/head branches, and `app/github_client.py` posts results back as a
GitHub Check Run. To wire this up for real:

1. Create a GitHub App at github.com/settings/apps/new (or your org's
   equivalent):
   - Webhook URL: your publicly-reachable `/webhooks/github` endpoint (use
     `ngrok http 8000` or similar for local testing — GitHub needs to reach it)
   - Webhook secret: generate one, save it as `GITHUB_WEBHOOK_SECRET`
   - Permissions: Repository → Pull requests: Read-only, Checks: Read & write,
     Metadata: Read-only
   - Subscribe to events: Pull request
2. Generate a private key for the app (Settings → your app → Generate a
   private key) and set it as `GITHUB_PRIVATE_KEY` (the full PEM contents).
3. Set `GITHUB_APP_ID` to the App ID shown on the app's settings page.
4. Install the app on a repo you control.

```bash
export GITHUB_APP_ID=...
export GITHUB_PRIVATE_KEY="$(cat path/to/your-app.private-key.pem)"
export GITHUB_WEBHOOK_SECRET=...
```

Then start the API and worker as below with those env vars set. Opening or
updating a PR on the installed repo should trigger a run automatically.

## Local setup

```bash
docker compose up -d          # Postgres on localhost:5432
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
PYTHONPATH=. ./.venv/bin/python -m procrastinate --app app.procrastinate_app.procrastinate_app schema --apply
```

(`PYTHONPATH=.` / `python -m` is needed so the `app` package resolves — the
plain `procrastinate` console script doesn't add the cwd to `sys.path`.)

Run the API (creates the `runs` table on startup):

```bash
./.venv/bin/uvicorn app.main:app --reload
```

Run the worker in a separate terminal:

```bash
PYTHONPATH=. ./.venv/bin/python -m procrastinate --app app.procrastinate_app.procrastinate_app worker
```

Try it:

```bash
curl -X POST localhost:8000/runs -H 'content-type: application/json' \
  -d '{"repo": "octocat/demo", "pr_number": 1}'
curl localhost:8000/runs/1
```
