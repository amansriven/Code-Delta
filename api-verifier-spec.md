# API Verifier — MVP Spec

## The problem

API pull requests often look safe in a code diff but silently change behavior:
a field that used to be optional becomes required, a status code changes from
`404` to `200`, an edge case (empty list, null, zero) starts throwing a 500.
Human reviewers skim diffs and rarely test every edge case by hand. Existing
AI PR-review tools (CodeRabbit, Copilot reviews, etc.) give subjective, LLM-opinion
comments like "consider whether this field could be null" — which is easy to
ignore and easy to distrust.

## The core idea (this is the differentiator — keep this no matter how the
## rest of the scope changes)

Instead of asking an LLM "does this code look risky," **generate concrete test
requests and actually run them against both the base branch and the PR
branch of the app.** Only report what demonstrably changed.

- Base passes, PR fails → **likely regression**, worth flagging
- Base fails, PR fails → pre-existing issue, not the PR's fault, don't flag
- Base fails, PR passes → possible fix, could note but not a warning
- Both pass → no regression, silent

This turns "AI thinks this might be a bug" into "this request returned 201 on
main and 500 on your PR" — evidence, not speculation. That's the whole value
proposition. Everything else in this spec exists to support this loop.

## MVP scope (deliberately narrow — do not build past this without checking in)

**Supported target repos, v1 only:**
- Python + FastAPI apps
- Expose a working `/openapi.json`
- Have a documented, simple startup command (e.g. `uvicorn app.main:app`)
- Can run locally without complex external dependencies (mock/stub anything
  that needs a real DB or third-party API for now)

Do NOT support other languages/frameworks yet. Do NOT build a hosted
multi-tenant execution system yet (no GitHub Actions orchestration, no
Celery/Redis, no S3). Run base vs. PR comparisons directly, synchronously,
on infrastructure you control (your own machine or a single small server) —
that's enough for building this out and testing on your own repos + a couple
of demo FastAPI repos built specifically to show this off.

## What v1 actually does, end to end

1. GitHub App receives a `pull_request` webhook (opened / synchronize)
2. Fetch the PR diff and both branches' `/openapi.json` (or the source, if
   the app needs to be started to generate it)
3. Diff the two OpenAPI specs to find which endpoints changed
4. For each changed endpoint, generate a small set of edge-case requests:
   - missing required field
   - omitted optional field
   - wrong data type
   - empty string / empty list / zero / negative number where applicable
   - (auth edge cases and multi-step flows are explicitly OUT of scope for v1
     — phase 2)
5. Spin up the base branch app and the PR branch app (locally, sequentially
   is fine for v1 — no need to parallelize)
6. Run the same generated requests against both
7. Compare results; keep only requests where base passed and PR failed
8. Post a single GitHub Check / PR comment listing only the reproduced
   regressions, with the exact request, base response, and PR response shown
9. Store the run (endpoint, requests generated, results, verdict) in Postgres

## Explicitly out of scope for v1 (phase 2+, don't build yet)

- GitHub Actions-based execution / sandboxing arbitrary repos
- Job queue (Celery/Redis) — synchronous is fine at this scale
- S3 or any artifact storage — Postgres rows are enough for now
- Authentication matrix testing (wrong user, expired token, etc.)
- Stateful multi-step flows (create → update → delete sequences)
- Flakiness detection (running each test N times)
- A full web dashboard with a test explorer / repo-specific learning
- Support for languages/frameworks other than FastAPI + pytest

## Suggested build order

**Phase 1 — Core loop, no GitHub integration yet (get this working first)**
- Given two versions of a small demo FastAPI app (base + a branch with an
  intentionally introduced bug), write the comparison engine: generate a few
  edge-case requests for one endpoint, run against both, diff the results
- Prove this works on a repo you built yourself before touching GitHub at all

**Phase 2 — OpenAPI-driven generation**
- Replace hand-written test cases with ones generated from the OpenAPI spec
  diff — detect which endpoints/fields changed, generate edge cases for those

**Phase 3 — GitHub App integration**
- Webhook listener, fetch PR + base branches, run the Phase 1/2 engine,
  post results as a GitHub Check or PR comment

**Phase 4 — Real usage**
- Install on your own projects first
- Track: PRs verified, regressions reproduced, false-positive rate (mark
  findings you disagree with) — these become your resume metrics

## Success metrics (decide what "good" means before or right after building)

- Regressions reproduced (with real examples, not just a count)
- False-positive rate — of what got posted, how many were actually real
- PRs verified
- A good resume line looks like: "Reproduced N regressions across M pull
  requests by running generated edge-case tests against base and PR branches,
  with X% confirmed real by maintainers" — not "flagged N issues."

## Suggested stack (matches what's realistic solo, not the full platform version)

- Backend: FastAPI (matches the target repos you're analyzing too)
- DB: Postgres
- GitHub integration: GitHub App (JWT auth, webhooks, Checks API)
- Test generation: start with deterministic rules off the OpenAPI diff;
  add an LLM pass later only for edge cases rules don't cover
- No frontend needed for v1 — GitHub Check output is the whole interface.
  A dashboard is a legitimate v2 addition once the core loop has real data
  to show.
