<p align="center">
  <img src="docs/assets/brand/codedelta-hero.png" alt="Code Delta — Your API changed. Know exactly how." width="900">
</p>

<p align="center">
  <strong>Evidence-first API regression detection for pull requests.</strong>
</p>

<p align="center">
  CodeΔ generates targeted edge-case requests, runs them against both sides of
  a pull request, and reports only the behavior that actually changed.
</p>

<p align="center">
  <img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-runs-4169E1?style=flat-square&logo=postgresql&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React-dashboard-20232A?style=flat-square&logo=react&logoColor=61DAFB">
  <img alt="Project stage" src="https://img.shields.io/badge/stage-MVP-70D6E7?style=flat-square">
</p>

---
## Live preview

CodeΔ is available at:

**[Open the CodeΔ dashboard](https://codedelta-frontend.amansriven757.workers.dev)**

> **Work in progress:** CodeΔ is under active development. Some features and interfaces may change. A custom production domain will be added in the future.

## Why CodeΔ?

API pull requests can look harmless in a code diff while silently changing
runtime behavior:

- an optional field becomes required;
- a missing resource changes from `404` to `200`;
- a valid payload starts returning `422`;
- an edge case that worked on `main` now produces a server error.

Traditional review tools can suggest that something *might* be wrong. CodeΔ
tests the change and shows what was observed:

```text
POST /items

Request
{ "name": "example", "price": 1.0 }

Base branch            Pull request
201 Created      →      422 Unprocessable Entity
discount: 0.0           discount: Field required
```

That distinction is the product:

> **The same request succeeded on the base branch and failed on the pull
> request. Here are both responses.**

No speculative verdict. No pre-existing failures. Just reproducible evidence.

## What CodeΔ does

1. Receives a pull-request event from GitHub.
2. Fetches the base and head revisions.
3. Reads and diffs both OpenAPI specifications.
4. Identifies changed endpoints, fields, and parameters.
5. Generates focused edge cases for the changed surface.
6. Starts both versions of the FastAPI application.
7. Sends the same requests to each version.
8. Keeps only requests whose behavior differs.
9. Stores the run and publishes the evidence as a GitHub Check Run.
10. Makes run history and response comparisons available to the dashboard.

### Finding semantics

| Finding | Meaning | Treatment |
| --- | --- | --- |
| `regression` | The base response succeeded, but the PR response failed. | High-severity evidence that the PR broke previously valid behavior. |
| `status_code_changed` | Both branches responded, but their status codes differ in another way. | A behavior change worth reviewing without automatically calling it a regression. |
| No finding | Both versions behaved equivalently, or both already failed. | Suppressed to keep review output focused. |

## How it works

```mermaid
flowchart LR
    GH["GitHub pull request"] --> WH["Webhook API"]
    WH --> DB[("PostgreSQL run")]
    DB --> Q["Procrastinate worker"]
    Q --> CLONE["Fetch base + head"]
    CLONE --> SPEC["Diff OpenAPI specs"]
    SPEC --> CASES["Generate edge cases"]
    CASES --> BASE["Run against base"]
    CASES --> HEAD["Run against PR"]
    BASE --> COMPARE["Compare responses"]
    HEAD --> COMPARE
    COMPARE --> RESULT["Reproduced findings"]
    RESULT --> CHECK["GitHub Check Run"]
    RESULT --> UI["CodeΔ dashboard"]
```

The job queue is backed by PostgreSQL through
[Procrastinate](https://procrastinate.readthedocs.io/), so the MVP does not
need Redis or Celery. Webhooks stay fast: they create a run, enqueue the work,
and return while a separate worker performs the comparison.

## Current capabilities

- OpenAPI-aware detection of changed request bodies, path parameters, and
  query parameters.
- Generated cases for omitted fields, required-field changes, and type
  changes.
- Real base-versus-head execution in isolated subprocesses.
- GitHub App webhook verification and Check Run publishing.
- Asynchronous run lifecycle: `pending → running → done | failed`.
- Persisted results, failure details, and retry support.
- Demo FastAPI applications with intentionally introduced regressions.
- Responsive dashboard for run history and side-by-side response evidence.
- Clearly distinguished regressions and non-regression behavior changes.
- GitHub OAuth sessions with repository-scoped dashboard authorization.
- Optional Ollama-assisted case generation and finding explanations, with a
  deterministic fallback when no model is configured.

## Supported repositories

CodeΔ deliberately keeps its first version narrow. A target repository should:

- use Python and FastAPI;
- expose a working `/openapi.json`;
- have a simple local startup path such as `uvicorn app.main:app`;
- run without complex external infrastructure, or provide local substitutes.

Other languages, frameworks, stateful multi-step workflows, authentication
matrices, and arbitrary multi-tenant code execution are outside the current
MVP.

## Repository structure

```text
CodeDelta/
├── app/
│   ├── main.py              # Runs API
│   ├── webhook.py           # GitHub webhook receiver
│   ├── tasks.py             # Background comparison jobs
│   ├── engine.py            # Base-vs-PR execution and response comparison
│   ├── cases.py             # Stable request-case identity and provenance
│   ├── openapi_diff.py      # Changed-surface detection and case generation
│   ├── llm.py               # Optional LLM case and explanation enrichment
│   ├── repo_fetch.py        # Base/head repository checkout
│   ├── github_client.py     # GitHub authentication and Check Runs
│   └── db.py                # PostgreSQL schema and connection
├── demo_apps/               # Base app plus intentionally broken variants
├── frontend/                # CodeΔ landing page and dashboard
├── docs/assets/brand/       # Repository-safe brand artwork
├── tests/                   # Unit and end-to-end engine tests
├── api-verifier-spec.md     # Product scope and design rationale
├── frontend-handoff.md      # Backend API shapes for the dashboard
├── docker-compose.yml       # Local PostgreSQL
├── pyproject.toml           # Python package, test, and lint configuration
└── requirements.txt
```

## Quick start

For a command-oriented setup and deployment guide, see
[docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md). The root Makefile
provides `make setup`, `make test`, local service commands, and deployment
helpers.

### Prerequisites

- Python 3.12+
- Docker
- Node.js 22.13+ for the frontend
- Git

### 1. Start PostgreSQL

```bash
docker compose up -d
```

The default local connection is:

```text
postgresql://codedelta:codedelta@localhost:5432/codedelta
```

### 2. Install the backend

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
PYTHONPATH=. ./.venv/bin/python -m procrastinate \
  --app app.procrastinate_app.procrastinate_app schema --apply
```

### 3. Start the API

```bash
./.venv/bin/uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`.

### 4. Start the worker

In a second terminal:

```bash
PYTHONPATH=. ./.venv/bin/python -m procrastinate \
  --app app.procrastinate_app.procrastinate_app worker
```

### 5. Run a local comparison

Manually created runs use the bundled base and buggy demo applications:

```bash
curl -X POST http://localhost:8000/runs \
  -H 'content-type: application/json' \
  -d '{"repo": "local/codedelta-demo", "pr_number": 1}'

curl http://localhost:8000/runs/1
```

### 6. Start the dashboard

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`. The dashboard uses clearly labeled preview data
by default. Set `NEXT_PUBLIC_CODEDELTA_API_URL` when connecting it to a hosted
API with the appropriate CORS and authentication configuration.

## Tests and quality checks

```bash
./.venv/bin/ruff check app tests
./.venv/bin/pytest -q

cd frontend
npm run lint
npm test
```

GitHub Actions runs the same backend and frontend checks for pull requests and
pushes to `main`.

## API overview

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Return the web service liveness status. |
| `GET` | `/auth/me` | Return the signed-in GitHub identity and accessible repositories. |
| `GET` | `/auth/github/login` | Begin the GitHub OAuth sign-in flow. |
| `POST` | `/auth/logout` | End the current dashboard session. |
| `GET` | `/runs` | Return the 50 most recent runs. |
| `GET` | `/runs/{id}` | Return a run and its reproduced findings. |
| `POST` | `/runs` | Create a manual comparison run for local testing. |
| `POST` | `/runs/{id}/retry` | Requeue a failed or completed run. |
| `POST` | `/webhooks/github` | Receive signed GitHub pull-request events. |

`result` remains `null` while a run is pending or running. Completed results
have the following shape:

```json
{
  "findings": [
    {
      "case": "omit_discount",
      "kind": "regression",
      "request": {
        "method": "POST",
        "path": "/items",
        "json": {
          "name": "example",
          "price": 1.0
        }
      },
      "base_response": {
        "status_code": 201,
        "body": {
          "discount": 0.0
        }
      },
      "pr_response": {
        "status_code": 422,
        "body": {
          "detail": "Field required"
        }
      }
    }
  ]
}
```

## GitHub App setup

The existing GitHub App integration handles repository events and Check Runs.
It is separate from the future GitHub OAuth App used to sign users into the
dashboard.

<details>
<summary><strong>Configure the repository GitHub App</strong></summary>

1. Create a GitHub App from your account or organization settings.
2. Set its webhook URL to the publicly reachable
   `https://your-api.example.com/webhooks/github`.
3. Generate a webhook secret.
4. Grant these repository permissions:
   - **Pull requests:** Read-only
   - **Checks:** Read and write
   - **Metadata:** Read-only
5. Subscribe to the **Pull request** event.
6. Generate a private key and install the app on a test repository.
7. Configure the environment variables below before starting the API and
   worker.

</details>

### Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Production | PostgreSQL connection string. A local default is provided. |
| `GITHUB_APP_ID` | GitHub integration | Numeric ID of the repository GitHub App. |
| `GITHUB_PRIVATE_KEY` | GitHub integration | Full PEM private key used to create installation tokens. |
| `GITHUB_WEBHOOK_SECRET` | GitHub integration | Secret used to validate webhook signatures. |
| `GITHUB_OAUTH_CLIENT_ID` | Dashboard login | Client ID for the GitHub OAuth App. |
| `GITHUB_OAUTH_CLIENT_SECRET` | Dashboard login | Client secret for the GitHub OAuth App. |
| `GITHUB_OAUTH_CALLBACK_URL` | Dashboard login | Public backend OAuth callback URL. |
| `FRONTEND_URL` | Hosted backend | Public frontend URL used after login and logout. |
| `OLLAMA_URL` | Optional AI | Ollama-compatible API base URL. |
| `OLLAMA_MODEL` | Optional AI | Model used to enrich generated cases and explanations. |
| `NEXT_PUBLIC_CODEDELTA_API_URL` | Hosted frontend | Public base URL of the CodeΔ API. |

Example local configuration:

```bash
export GITHUB_APP_ID="..."
export GITHUB_PRIVATE_KEY="$(cat path/to/code-delta.private-key.pem)"
export GITHUB_WEBHOOK_SECRET="..."
```

Never commit private keys, webhook secrets, or production database
credentials.

## Product boundaries and security

The GitHub App handles repository webhooks and Check Runs. A separate GitHub
OAuth App signs users into the dashboard. Run reads and retries are restricted
to repositories returned by the signed-in user's matching GitHub App
installations. Production credentials must remain in the hosting platforms'
secret stores, and the authenticated API should only be called from an allowed
frontend origin.

## Roadmap

- [x] Deterministic OpenAPI diffing
- [x] Targeted edge-case generation
- [x] Base-versus-PR execution
- [x] GitHub webhooks and Check Runs
- [x] PostgreSQL-backed job queue
- [x] Failure state and run retries
- [x] Dashboard experience
- [x] Production backend deployment
- [x] GitHub OAuth and secure sessions
- [x] Repository-level dashboard authorization
- [x] Hosted frontend-to-API integration
- [x] Optional LLM-assisted case generation and explanations
- [ ] Pagination, filtering, and operational monitoring

## Brand assets

<p align="center">
  <img src="docs/assets/brand/codedelta-badge.png" alt="Code Delta dark badge" width="260">
  &nbsp;&nbsp;&nbsp;
  <img src="docs/assets/brand/codedelta-mark.png" alt="Code Delta standalone mark" width="180">
</p>

The full product brief is available in
[api-verifier-spec.md](api-verifier-spec.md), and the dashboard API handoff is
documented in [frontend-handoff.md](frontend-handoff.md).

---

<p align="center">
  <strong>CodeΔ</strong><br>
  Evidence, not speculation.
</p>
