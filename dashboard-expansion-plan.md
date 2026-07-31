# Delta Code Dashboard Expansion Plan (v2)

Handoff spec for the next round of frontend work. `frontend-plan.md` covered
v1 (landing page, runs list, basic run detail, GitHub OAuth) — that's now
fully built and live at https://codedelta-frontend.amansriven757.workers.dev,
backed by a real API at https://web-production-e59907.up.railway.app. Real
GitHub OAuth, server-side sessions, and repo-scoped access control are done
and verified against a live GitHub account. Sign-out also just shipped.

This plan covers the four gaps identified after using the live v1 site: only
two pages exist, and Integrations is static demo copy rather than a real
account/repo management surface. Four features, roughly in priority order.

## What's already true (don't rebuild)

- `liveApiUrl` (from `NEXT_PUBLIC_DELTA_CODE_API_URL`) gates demo vs. live data
  throughout `DeltaCodeApp.tsx` — keep using this pattern.
- `app/lib/data.ts` has `fetchRuns`, `fetchRun`, `fetchMe`, `signOut`,
  `githubLoginUrl`, all already using `credentials: "include"` for the
  cross-site session cookie. Reuse these; don't re-implement fetch logic.
- `AppHeader` already fetches the current user via `fetchMe()` and renders a
  working account dropdown with sign-out. Extend it, don't replace it.
- All `/runs` and `/runs/{id}` API calls are session-gated and filtered to
  repos the signed-in user can access — this is enforced server-side, not
  just hidden in the UI. No frontend change can accidentally leak another
  user's data through these endpoints.

## API surface available now

### `GET /auth/me`
```json
{
  "login": "amansriven",
  "avatar_url": "https://avatars.githubusercontent.com/u/189822438?v=4",
  "accessible_repos": ["amansriven/codedelta-demo-app"],
  "repositories": [
    {
      "full_name": "amansriven/codedelta-demo-app",
      "private": false,
      "visibility": "public"
    }
  ]
}
```
401 if not signed in. `accessible_repos` is exactly the repos the signed-in
user can access through the CodeDeltaApp GitHub App installation(s) they're a
member of. `repositories` carries the same access list with visibility
metadata for the settings UI.

### `GET /runs/{id}` (now includes branch info)
```json
{
  "id": 14,
  "repo": "amansriven/codedelta-demo-app",
  "pr_number": 1,
  "status": "done",
  "result": { "findings": [...] },
  "error": null,
  "base_ref": "main",
  "base_sha": "a41cf885b21389c37fd634339045833664a75025",
  "head_ref": "introduce-discount-bug",
  "head_sha": "d641d9ce5d92c8b847634219672d8be48200b20e",
  "created_at": "...",
  "updated_at": "..."
}
```
`error` is populated (a Python traceback string) when `status === "failed"`.

### `POST /runs/{id}/retry`
Re-enqueues a run (resets to `pending`, clears `result`/`error`). Returns
`{"id": ..., "status": "pending"}`. **Not currently wired to any UI** — this
is a real gap, not a planning placeholder.

### `GET /runs`
Unchanged: lightweight list with `finding_count`/`highest_severity`, capped
at 50 most recent, filtered to accessible repos.

### Installing the App on more repos
No backend endpoint needed — GitHub's own install page handles this:
`https://github.com/apps/codedeltaapp/installations/new`. Opening it in a new
tab and letting the user pick repos is sufficient; there's no callback needed
for the installation itself. After changing the selection, repeat GitHub
authorization from the settings page so the server can refresh the
repository-scoped session.

## Feature 1: Make Integrations functional

Currently: static "Preview identity" / "Demo workspace owner" copy and a
"Backend connection required" card — entirely disconnected from real state.

Build:
- Real identity card: avatar + login from `fetchMe()`, not hardcoded text.
- Real repo list: render `accessible_repos` from the same call. Empty state
  if the list is empty ("No repositories connected yet").
- "Install on more repos" button linking to the GitHub install URL above
  (`target="_blank"`), with a note that repos appear here after granting
  access.
- Remove the "Backend connection required" messaging entirely — the backend
  connection is real now.
- If not signed in, show the same sign-in prompt pattern already used on
  `/runs` (see `githubLoginUrl` usage there) rather than a separate flow.

## Feature 2: Richer run detail page

Currently: findings list only, no branch/commit context, no retry action.

Build:
- Show `base_ref`/`head_ref` (and shortened `base_sha`/`head_sha`, e.g. first
  7 chars) near the top of the run detail — this is now in the API response.
- Link to the actual PR: `https://github.com/{repo}/pull/{pr_number}`.
- A "Retry" button that calls `POST /runs/{id}/retry`, then re-fetches the
  run (or polls) to show updated status. Should be visible at least when
  `status === "failed"`; showing it always is fine too.
- When `status === "failed"`, display the `error` field (it's a full Python
  traceback — render in a `<pre>` or collapsible block, not inline text).
- Base-vs-PR response comparison already exists for findings; consider a
  cleaner side-by-side diff (e.g. highlight which JSON keys differ) if time
  allows, but this is polish, not required.

## Feature 3: Per-repo view

Currently: one flat run list, no grouping or per-repo trends.

Build:
- A view (could be a tab/toggle on `/runs`, or its own route like
  `/runs?groupBy=repo`) that groups the existing `GET /runs` response
  client-side by `repo` — no new backend endpoint needed for v1 of this.
- Per repo, show: run count, regression count (count of
  `highest_severity === "regression"`), last run timestamp.
- **Known limitation to surface in the UI or just accept for now**: `GET
  /runs` caps at 50 most recent runs across *all* repos, so a repo with heavy
  activity could be undercounted if older runs fall off the list. Fine for
  current usage levels; flag as a future backend enhancement (a dedicated
  aggregation endpoint) rather than solving it now.

## Feature 4: Account/settings page

Overlaps with Feature 1 — recommend building both under one `/settings` area
(e.g. tabs: "Account" and "Repositories") rather than as fully separate pages,
to avoid page-count bloat for what's conceptually one settings surface.

Build:
- Account tab: avatar, GitHub login, maybe GitHub profile link
  (`https://github.com/{login}`). Sign-out already works from the header
  dropdown — decide whether to duplicate it here or just rely on the header.
- No new backend needed beyond `fetchMe()`.

## Non-goals for this round

- Don't touch the backend (`app/*.py`) — flag any gap found back to me
  instead of implementing backend changes directly, to avoid the two of us
  stepping on each other.
- Don't rebuild the visual design language already established (graphite
  surfaces, cyan accent, existing component patterns in `globals.css`) —
  extend it.
- Don't add pagination/infinite-scroll for the 50-run cap — out of scope
  until it's an actual problem.
