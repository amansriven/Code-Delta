# Phase 5 — GitHub publishing

Phase 5 projects a completed migration attempt into GitHub without making
GitHub the source of truth. Publication is a deliberate, authenticated action:
Delta Code does not automatically open a pull request merely because generation
recommended approval.

## Implemented flow

1. `POST /migrations/{migration_id}/publish` requires a trusted browser origin,
   workspace authorization, an idempotency key, the current migration version,
   and the explicit `GITHUB_PUBLISHING_ENABLED=true` release gate.
2. The transaction accepts only a `ready` migration (or a retryable publishing
   blocker) whose current attempt is terminal, recommends approval, and has
   entirely passing deterministic checks. It locks the exact structured-patch
   artifact and moves the migration to `pr_opening`.
3. A background job obtains a short-lived GitHub App installation token from an
   opaque installation handle. Before any write, the returned installation
   permissions must show `contents`, `pull_requests`, and `checks` at `write`.
4. The publisher verifies that the repository's base branch still points to the
   exact Phase 4 snapshot commit. An advanced base is a blocker; the publisher
   never silently rebases or regenerates.
5. The immutable patch artifact is re-read from content-addressed storage,
   digest-checked, canonical-JSON checked, path-policy checked, and converted to
   a Git tree based on the verified base tree. Existing executable modes are
   preserved.
6. GitHub receives one tree and one commit. A collision-resistant Delta
   Code-owned branch is created without force. An unexpected existing branch
   fails before Git objects are written.
7. GitHub opens a draft pull request with `maintainer_can_modify=false`. Its
   bounded body is rendered only from structured evidence and does not include
   raw logs or credentials.
8. A completed GitHub Check Run is attached to that exact commit. Tree, commit,
   branch, pull-request, and check identifiers are persisted as individual
   resumable checkpoints, with an audit event for every external write.
9. Completion moves the migration to `pr_opened`. `GET
   /migrations/{migration_id}/publication` exposes workspace-scoped publication
   state without exposing installation credentials.

The implementation uses GitHub's current REST endpoints for [Git trees](https://docs.github.com/en/rest/git/trees),
[Git commits](https://docs.github.com/en/rest/git/commits),
[references](https://docs.github.com/en/rest/git/refs),
[draft pull requests](https://docs.github.com/en/rest/pulls/pulls), and
[check runs](https://docs.github.com/en/rest/checks/runs). The API version is
pinned to `2026-03-10`.

## Revision synchronization

A migration owns one publication record and one Delta Code branch. When a
developer requests revision, Phase 4 creates a new immutable attempt. Publishing
that later `ready` attempt creates a new sibling commit from its verified base,
then updates the existing owned branch and draft rather than opening another PR.

Before that update, the publisher requires all of the following:

- the pull request is still open and draft;
- its head equals Delta Code's recorded remote head;
- the owned branch equals that same recorded head;
- the repository base still equals the new attempt's verified base.

Only then may the publisher force-update its own branch. Human changes, a
manually readied/closed draft, an advanced base, or a moved branch fail closed.

## Developer decisions

With publishing enabled, `approve` first verifies the recorded head and uses
GitHub's
[`markPullRequestReadyForReview`](https://docs.github.com/en/graphql/reference/pulls#markpullrequestreadyforreview)
mutation. It never invokes a merge mutation. `decline` verifies the same head
and closes the PR. Revision leaves the current PR draft so the next successful
attempt can synchronize it; snooze leaves it untouched.

GitHub writes occur before the optimistic database decision. If the database
version changes concurrently, the request returns a conflict and the same
idempotent action can be reconciled safely; every successful external action is
audited immediately.

## Write-permission gate

The GitHub App installation must be visibly reauthorized with only:

| Permission | Required level | Use |
|---|---:|---|
| Contents | Read and write | Trees, commits, and owned branch refs |
| Pull requests | Read and write | Create/update drafts and mark ready/close |
| Checks | Read and write | Publish exact-commit verification evidence |

Do not grant Actions, Workflows, Administration, Deployments, Environments,
Secrets, Members, or organization-administration permissions. Phase 4 and the
publisher continue to reject `.github/workflows/**` edits.

The release sequence is:

1. deploy the Phase 5 code while `GITHUB_PUBLISHING_ENABLED` is absent;
2. update the GitHub App permissions and require installation reauthorization;
3. verify a controlled repository's stale-base, branch-collision, revoked-token,
   partial-failure, revision, ready, and close paths;
4. audit the created branch, commit, PR, and Check Run;
5. set `GITHUB_PUBLISHING_ENABLED=true` only for the approved environment.

Revoking permissions or disabling the flag blocks new writes independently of
ingestion, analysis, and sandbox execution.

## Current boundary

Phase 5 creates and maintains draft PRs and their evidence checks. It does not
merge, enable auto-merge, modify repository settings, bypass protection rules,
or delete branches. Merge observation and the migration inbox experience remain
later phases.
