# Delta Code development and hosting runbook

The root `Makefile` is the shortest path for normal development. Run `make
help` at any time to see the available commands.

## Prerequisites

- Python 3.12 or newer
- Node.js 22.13 or newer
- Docker with Compose
- Git
- GNU Make or the Make version included with macOS

Railway CLI and the Vercel CLI are only required for command-line deployment.

## First-time setup

```bash
make setup
make db-up
make db-schema
```

`make setup` creates `.venv`, installs the backend in editable mode with test
dependencies, runs `npm ci` in `frontend/` and `sandbox-worker/`, and creates
`frontend/.env` if it does not exist. The default frontend API is the live
Railway service:

```text
NEXT_PUBLIC_DELTA_CODE_API_URL=https://web-production-e59907.up.railway.app
```

Override it without editing the Makefile:

```bash
make frontend-dev LIVE_API_URL=http://localhost:8000
```

## Run the application locally

Use three terminals after PostgreSQL is running.

Terminal 1 — API:

```bash
make api
```

Terminal 2 — comparison worker:

```bash
make worker
```

The same worker also runs official-source synchronization, repository
intelligence, and migration-generation jobs. Repository analysis checks out the
GitHub default branch ephemerally. Generation checks out the exact stored
snapshot commit, validates its digest, and removes the checkout after the job.

Terminal 3 — dashboard:

```bash
make frontend-dev
```

The services are available at:

| Service | URL |
| --- | --- |
| Dashboard | `http://localhost:3000` |
| API | `http://localhost:8000` |
| API health | `http://localhost:8000/health` |
| PostgreSQL | `postgresql://deltacode:deltacode@localhost:5432/deltacode` |

The API and worker read configuration from environment variables. Export
GitHub App and OAuth values in the shell before starting them when testing
webhooks, Check Runs, or the complete sign-in flow:

```bash
export GITHUB_APP_ID="..."
export GITHUB_PRIVATE_KEY="..."
export GITHUB_WEBHOOK_SECRET="..."
export GITHUB_OAUTH_CLIENT_ID="..."
export GITHUB_OAUTH_CLIENT_SECRET="..."
export GITHUB_OAUTH_CALLBACK_URL="http://localhost:8000/auth/github/callback"
export FRONTEND_URL="http://localhost:3000"
export ARTIFACT_STORAGE_ROOT="$PWD/.delta-code-artifacts"
export MIGRATION_INTELLIGENCE_URL="https://your-gateway.example"
export MIGRATION_INTELLIGENCE_TOKEN="..."
export SANDBOX_EXECUTOR_URL="https://your-sandbox-worker.example.workers.dev"
export SANDBOX_EXECUTOR_TOKEN="..."
# Enable only after the Phase 4 isolation checklist has passed.
export SANDBOX_EXECUTION_ENABLED="true"
```

Do not commit those values. Basic pages and the signed-out live-API state work
without GitHub credentials.

`ARTIFACT_STORAGE_ROOT` holds immutable Phase 2 source captures. The local path
is ignored by Git. Hosted ingestion requires an encrypted persistent volume;
the worker's `/tmp` fallback is suitable only for tests and local evaluation.

Private repository verification additionally requires the GitHub App to have
read-only **Contents** permission. Install or update the app on the private
repository, then use **Refresh repository access** in the dashboard settings
to repeat GitHub authorization and refresh the session's repository list.
The refreshed OAuth session records each repository's clone URL, default
branch, and GitHub App installation id; existing sessions must be refreshed
before Phase 3 jobs can check out those repositories.

## Test and build

Run the same checks used in CI:

```bash
make test
```

Individual commands:

```bash
make lint
make test-backend
make test-frontend
make test-sandbox
make build
make health
```

The backend integration test starts temporary demo FastAPI servers on local
ephemeral ports. If a restricted shell forbids local socket binding, run the
test from a normal terminal.

## Database operations

```bash
make db-up
make db-schema
make db-logs
make db-down
```

`db-down` stops containers but preserves the named PostgreSQL volume.

## Deploy the hosted services

Authenticate the Railway and Vercel CLIs before the first command-line
deployment. The Railway project must be linked to this repository and contain
services named `web` and `worker`. The Vercel project should be named
`deltacode` and use `frontend` as its root directory.

Deploy both Railway services and wait for each build to finish:

```bash
make deploy-backend
```

Deploy only one service:

```bash
make deploy-web
make deploy-worker
```

Build and deploy the native Next.js frontend to Vercel production:

```bash
make deploy-frontend
```

Deploy all three services:

```bash
make deploy
```

Use another Railway environment with:

```bash
make deploy-backend RAILWAY_ENV=staging
```

After deployment, verify the public backend:

```bash
make health-live
```

Set `NEXT_PUBLIC_DELTA_CODE_API_URL` in Vercel. Set Railway's `FRONTEND_URL` to
the canonical Vercel production URL, and add any additional trusted preview
origins to `ALLOWED_ORIGINS` as a comma-separated list.

The production service variables remain managed by Railway and Vercel;
the Makefile never embeds database credentials, GitHub secrets, or private
keys.
