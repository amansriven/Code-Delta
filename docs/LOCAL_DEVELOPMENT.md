# Code Delta development and hosting runbook

The root `Makefile` is the shortest path for normal development. Run `make
help` at any time to see the available commands.

## Prerequisites

- Python 3.12 or newer
- Node.js 22.13 or newer
- Docker with Compose
- Git
- GNU Make or the Make version included with macOS

Railway CLI and Wrangler are only required for deployment.

## First-time setup

```bash
make setup
make db-up
make db-schema
```

`make setup` creates `.venv`, installs the backend in editable mode with test
dependencies, runs `npm ci` in `frontend/`, and creates `frontend/.env` if it
does not exist. The default frontend API is the live Railway service:

```text
NEXT_PUBLIC_CODEDELTA_API_URL=https://web-production-e59907.up.railway.app
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
| PostgreSQL | `postgresql://codedelta:codedelta@localhost:5432/codedelta` |

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
```

Do not commit those values. Basic pages and the signed-out live-API state work
without GitHub credentials.

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

Authenticate the Railway and Cloudflare CLIs before the first deployment. The
Railway project must be linked to this repository and contain services named
`web` and `worker`.

Deploy both Railway services and wait for each build to finish:

```bash
make deploy-backend
```

Deploy only one service:

```bash
make deploy-web
make deploy-worker
```

Build and deploy the Vinext Cloudflare Worker:

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

The production service variables remain managed by Railway and Cloudflare;
the Makefile never embeds database credentials, GitHub secrets, or private
keys.
