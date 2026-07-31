# Delta Code Frontend Implementation Plan

## 1. Product objective

Build a calm, polished dashboard that makes Delta Code's core value immediately
clear: it reports reproduced API behavior changes, not speculative code-review
advice.

The frontend must make it easy to:

1. Understand the product before signing in.
2. Connect Delta Code to GitHub.
3. See recent pull-request verification runs.
4. Distinguish confirmed regressions from other status-code changes.
5. Inspect the exact request and compare base and PR responses.
6. Understand queued, running, successful, empty, and failed states.

The first implementation will be a working product demo connected to the
existing API where available. Secure hosted GitHub authentication remains a
backend capability: the current API has no user, session, or authorization
model and must not be exposed publicly as-is.

## 2. Experience principles

### Evidence first

The exact HTTP request and the base-versus-PR response comparison are the
primary content. Decorative dashboard metrics are secondary.

### Calm technical confidence

Use graphite surfaces, restrained cyan accents, readable typography, and
purposeful status colors. Avoid neon cyberpunk styling, excessive gradients,
glass effects, and dense terminal aesthetics.

### Progressive detail

The runs list should be scannable. Technical payloads appear only after opening
a run, and long response bodies remain readable without dominating the page.

### Honest system boundaries

The frontend may demonstrate GitHub sign-in and installation states, but it
must not present a client-only toggle as secure authentication. Real hosted
authentication requires backend OAuth callbacks, secure sessions, and
repository-level authorization.

## 3. Brand system

### Wordmark

- Display name: `Delta Code`
- Accessible name: `Delta Code`
- Treatment: neutral `Code` wordmark with the `Δ` in the product accent color
- The wordmark should be rendered as text/CSS so it stays crisp and accessible
- The delta may sit inside a subtle outlined container when used as an app icon

### Voice

- Direct and technically literate
- Short, factual headlines
- Prefer “reproduced,” “observed,” and “changed” over speculative language
- Explain severity without claiming certainty beyond the recorded responses

### Visual tokens

- Canvas: deep neutral graphite
- Raised surfaces: slightly lighter cool slate
- Primary text: soft white
- Secondary text: cool gray
- Accent: cyan-blue
- Regression: coral-red
- Status-code change: amber
- Success/no findings: emerald
- Pending/running: blue
- Borders: low-contrast slate
- UI type: Geist/Inter-compatible system sans
- Technical type: JetBrains Mono-compatible system monospace

## 4. Information architecture

### `/`

Public landing page:

- Delta Code value proposition
- Short explanation of base-versus-PR verification
- Interactive-looking evidence preview using realistic product data
- “Continue with GitHub” primary action
- Secondary link into the demo dashboard

### `/login`

Focused sign-in page:

- Product reassurance and privacy copy
- GitHub sign-in action
- Explanation that GitHub identity and GitHub App installation are separate
- Demo access for the current frontend preview

### `/onboarding`

Three-step setup:

1. GitHub identity connected
2. GitHub App installation
3. Repository access confirmation

The production actions will be represented honestly as integration points until
the backend implements OAuth and installation APIs.

### `/runs`

Authenticated product shell:

- Summary of recent verification activity
- Search by repository or pull request
- Filter by status
- Compact responsive runs table
- Clear status, severity, finding count, and timestamp
- Empty, loading, unavailable, and filtered-empty states

### `/runs/:runId`

Run detail:

- Repository, PR, status, and timing context
- Overall verdict summary
- Finding navigation
- Request method, path, and payload
- Side-by-side base and PR status/body comparison
- Responsive stacked comparison on narrow screens
- Clear distinction between `regression` and `status_code_changed`
- Pending/running state with automatic refresh

### `/settings/integrations`

Lightweight integration view:

- Connected GitHub identity
- GitHub App installation state
- Repository access summary
- Clear labeling of demo versus live integration state

## 5. Application architecture

### Framework

- React and TypeScript
- Vite-compatible Sites project
- React Router for client-side navigation
- Small typed API module rather than calls scattered through components
- CSS design tokens and component-level styles

### Main modules

- `brand`: wordmark and compact app mark
- `public-shell`: landing, sign-in, and onboarding layout
- `app-shell`: product header, navigation, account menu, and mobile navigation
- `runs`: filters, status badges, list/table, and summary
- `run-detail`: finding cards, request panel, and response comparison
- `data`: API types, fetch client, polling rules, and demo fixtures
- `system-state`: loading, empty, error, and unavailable presentations

### Data model

Model the current backend response exactly:

- Run summary: `id`, `repo`, `pr_number`, `status`, `created_at`
- Run detail: summary fields plus `result`, `updated_at`
- Finding: `case`, `kind`, `request`, `base_response`, `pr_response`

Allow additive optional frontend fields such as finding count, refs, and commit
SHAs so the UI is ready for the backend's planned extensions.

### API behavior

- Fetch `GET /runs` for the dashboard
- Fetch `GET /runs/:id` for detail
- Poll a detail run while its status is `pending` or `running`
- Keep manual `POST /runs` out of the primary interface because webhook-created
  runs are the normal product flow
- Use deterministic demo fixtures when the preview is intentionally in demo
  mode
- Never silently replace a failed live API request with demo data; label demo
  mode explicitly

## 6. Authentication and authorization plan

### Frontend milestone

- Implement sign-in, onboarding, account, and integration screens
- Provide a clearly labeled demo session for the preview
- Keep production GitHub actions as explicit backend integration boundaries

### Required backend milestone before public launch

1. GitHub OAuth authorization endpoint
2. OAuth callback handled server-side
3. Secure, HTTP-only session cookie
4. Current-user/session endpoint
5. Sign-out endpoint
6. GitHub App installation discovery
7. Repository access and run authorization
8. CSRF protection for state-changing requests
9. Production CORS and cookie policy

OAuth identifies the user. The GitHub App installation grants repository
access. Both must be checked server-side before returning run data.

## 7. Responsive behavior

- Desktop: compact top navigation, data table, side-by-side response comparison
- Tablet: reduced metadata columns and flexible cards
- Mobile: stacked navigation, run cards, and stacked response panels
- No essential action may depend on hover
- Code payloads scroll horizontally without forcing page-level overflow

## 8. Accessibility

- Semantic landmarks and headings
- Visible keyboard focus
- Skip-to-content link
- Accessible names for the Delta Code wordmark and icon-only controls
- Status meaning communicated with text/icons as well as color
- Sufficient contrast for text and controls
- Reduced-motion support
- Tables retain meaningful headers; mobile cards preserve equivalent labels
- Live status updates avoid disruptive announcements

## 9. System states

Every data surface will account for:

- Initial loading
- Pending
- Running
- Done with no findings
- Done with regressions
- Done with non-regression status changes
- API unavailable
- Unknown run
- Filtered-empty results
- Backend failure state when the API begins returning one

## 10. Backend improvements recommended after the frontend milestone

1. Add `failed` status and a safe error message.
2. Add `finding_count` and highest severity to `GET /runs`.
3. Return base/head refs and commit SHAs from run detail.
4. Add pagination and repository filters.
5. Add authenticated user and repository authorization.
6. Provide a health/readiness endpoint for connection state.

## 11. Validation plan

- Type-check and production build
- Unit coverage for status/severity mapping and API normalization
- Component coverage for empty, running, completed, and error states
- Route coverage for landing, login, onboarding, runs, and run detail
- Keyboard navigation and reduced-motion checks
- Responsive review at mobile, tablet, and desktop breakpoints
- Confirm no live API failure is mistaken for demo mode

## 12. Delivery sequence

1. Establish the project and route skeleton.
2. Implement tokens, global styles, and shared shells.
3. Build public landing and login.
4. Build onboarding and integration settings.
5. Build runs dashboard with realistic fixtures.
6. Build run detail and evidence comparison.
7. Add typed API connectivity and polling.
8. Add complete system states and accessibility behavior.
9. Run automated validation and fix failures.
10. Produce a private preview and document remaining backend integration work.

## 13. Definition of done

The milestone is complete when:

- All planned routes render and navigate correctly.
- The product consistently uses the `Delta Code` identity.
- Runs are scannable and findings are technically clear.
- Base and PR responses are easy to compare on desktop and mobile.
- Demo mode is clearly labeled.
- The frontend can consume the current `/runs` endpoints.
- Authentication screens do not misrepresent client-only state as security.
- The production build passes.
- A private preview is available for review.
