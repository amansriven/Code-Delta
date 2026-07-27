# CodeDelta

See [api-verifier-spec.md](api-verifier-spec.md) for the product spec.

## Job queue

Runs are tracked in a `runs` table in Postgres and processed asynchronously via
[procrastinate](https://procrastinate.readthedocs.io/) (a Postgres-backed task
queue — no Redis/Celery needed). `POST /runs` inserts a row and enqueues a job;
a separate `procrastinate worker` process picks it up and updates the row's
status as it runs. This keeps webhook handlers fast (insert + enqueue, return
immediately) and gives the future dashboard a table to poll/query for status.

`app/tasks.py::run_comparison` is currently a placeholder — swap its body for
the real base-vs-PR comparison engine (spec Phase 1) once that exists.

## Local setup

```bash
docker compose up -d          # Postgres on localhost:5432
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/procrastinate --app app.procrastinate_app.procrastinate_app schema --apply
```

Run the API (creates the `runs` table on startup):

```bash
./.venv/bin/uvicorn app.main:app --reload
```

Run the worker in a separate terminal:

```bash
./.venv/bin/procrastinate --app app.procrastinate_app.procrastinate_app worker
```

Try it:

```bash
curl -X POST localhost:8000/runs -H 'content-type: application/json' \
  -d '{"repo": "octocat/demo", "pr_number": 1}'
curl localhost:8000/runs/1
```
