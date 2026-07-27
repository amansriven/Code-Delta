"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CurrentUser,
  demoDetails,
  demoRuns,
  fetchMe,
  fetchRun,
  fetchRuns,
  Finding,
  FindingKind,
  githubLoginUrl,
  liveApiUrl,
  RunDetail,
  RunStatus,
  RunSummary,
  signOut,
} from "./lib/data";

const PRODUCT_NAME = "Code Delta";

function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <a className={`wordmark ${compact ? "wordmark-compact" : ""}`} href="/" aria-label={PRODUCT_NAME}>
      <span className="wordmark-code">Code</span>
      <span className="wordmark-delta">Δ</span>
    </a>
  );
}

function DemoPill() {
  return (
    <span className="demo-pill">
      <span className="demo-dot" aria-hidden="true" />
      Preview data
    </span>
  );
}

function PublicHeader() {
  return (
    <header className="public-header">
      <Wordmark />
      <nav aria-label="Public navigation">
        <a className="nav-link" href="#how-it-works">
          How it works
        </a>
        <a className="button button-quiet button-small" href={githubLoginUrl}>
          Sign in
        </a>
      </nav>
    </header>
  );
}

function AppHeader({ active }: { active: "runs" | "settings" }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchMe(controller.signal).then(setUser).catch(() => setUser(null));
    return () => controller.abort();
  }, []);

  const initials = user?.login ? user.login.slice(0, 2).toUpperCase() : "AS";

  return (
    <header className="app-header">
      <div className="app-header-inner">
        <Wordmark />
        <nav className="app-nav" aria-label="Dashboard navigation">
          <a className={active === "runs" ? "active" : ""} href="/runs">
            Runs
          </a>
          <a
            className={active === "settings" ? "active" : ""}
            href="/settings/integrations"
          >
            Integrations
          </a>
        </nav>
        <div className="account-cluster">
          {!liveApiUrl && <DemoPill />}
          <div className="account-menu">
            <button
              type="button"
              className="avatar"
              aria-label={user ? `Signed in as ${user.login}` : "Account menu"}
              aria-haspopup="true"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
            >
              {initials}
            </button>
            {menuOpen && (
              <div className="account-dropdown" role="menu">
                <span className="account-dropdown-name">
                  {user ? user.login : "Not signed in"}
                </span>
                {user ? (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      signOut().finally(() => {
                        window.location.href = "/";
                      });
                    }}
                  >
                    Sign out
                  </button>
                ) : (
                  <a role="menuitem" href={githubLoginUrl}>
                    Sign in with GitHub
                  </a>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

function StatusBadge({ status }: { status: RunStatus }) {
  const labels: Record<RunStatus, string> = {
    pending: "Queued",
    running: "Running",
    done: "Complete",
    failed: "Failed",
  };
  return (
    <span className={`status-badge status-${status}`}>
      <span className="status-dot" aria-hidden="true" />
      {labels[status]}
    </span>
  );
}

function SeverityBadge({ kind }: { kind: FindingKind }) {
  return (
    <span className={`severity-badge severity-${kind}`}>
      <span aria-hidden="true">{kind === "regression" ? "!" : "↕"}</span>
      {kind === "regression" ? "Regression" : "Behavior changed"}
    </span>
  );
}

function formatRelativeDate(value: string) {
  const timestamp = new Date(value).getTime();
  const minutes = Math.round((Date.now() - timestamp) / 60000);
  if (Math.abs(minutes) < 60) {
    return `${Math.max(1, minutes)}m ago`;
  }
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) {
    return `${hours}h ago`;
  }
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function repoParts(repo: string) {
  const [owner, name] = repo.split("/");
  return { owner: owner || "repository", name: name || repo };
}

function EvidencePreview() {
  return (
    <div className="evidence-window" aria-label="Example reproduced regression">
      <div className="window-bar">
        <span className="window-lights" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span>PR #128 · verification</span>
        <span className="verified-label">Reproduced</span>
      </div>
      <div className="evidence-content">
        <div className="finding-heading">
          <SeverityBadge kind="regression" />
          <span className="case-name">omit_discount</span>
        </div>
        <div className="request-line">
          <span className="method method-post">POST</span>
          <code>/items</code>
        </div>
        <div className="preview-compare">
          <div className="response-preview response-base">
            <div>
              <span>BASE</span>
              <strong className="code-success">201</strong>
            </div>
            <code>{`{ "discount": 0.0 }`}</code>
          </div>
          <div className="compare-arrow" aria-hidden="true">
            →
          </div>
          <div className="response-preview response-pr">
            <div>
              <span>PR</span>
              <strong className="code-danger">422</strong>
            </div>
            <code>{`{ "detail": "Field required" }`}</code>
          </div>
        </div>
      </div>
    </div>
  );
}

function LandingPage() {
  return (
    <main className="public-page">
      <PublicHeader />
      <section className="hero">
        <div className="hero-copy">
          <div className="eyebrow">
            <span />
            Behavioral regression detection
          </div>
          <h1>
            Your API changed.
            <br />
            <em>Know exactly how.</em>
          </h1>
          <p>
            CodeΔ runs the same edge-case requests against your base branch and
            pull request—then reports only the behavior that actually changed.
          </p>
          <div className="hero-actions">
            <a className="button button-primary" href={githubLoginUrl}>
              Continue with GitHub <span aria-hidden="true">→</span>
            </a>
            <a className="button button-quiet" href="/runs">
              Explore the demo
            </a>
          </div>
          <div className="hero-proof">
            <span className="proof-mark" aria-hidden="true">
              ✓
            </span>
            Evidence from real requests. No LLM verdicts.
          </div>
        </div>
        <div className="hero-visual">
          <div className="ambient ambient-one" />
          <div className="ambient ambient-two" />
          <EvidencePreview />
        </div>
      </section>
      <section className="principles" id="how-it-works">
        <article>
          <span className="principle-number">01</span>
          <h2>Detect what changed</h2>
          <p>CodeΔ reads the OpenAPI diff and targets the endpoints touched by the PR.</p>
        </article>
        <article>
          <span className="principle-number">02</span>
          <h2>Run both versions</h2>
          <p>The exact same generated requests run against the base and head branches.</p>
        </article>
        <article>
          <span className="principle-number">03</span>
          <h2>Show the evidence</h2>
          <p>Only reproduced behavior changes reach the dashboard and GitHub check.</p>
        </article>
      </section>
      <footer className="public-footer">
        <Wordmark compact />
        <p>Evidence, not speculation.</p>
      </footer>
    </main>
  );
}

function LoginPage() {
  return (
    <main className="auth-page">
      <div className="auth-brand">
        <Wordmark />
        <a className="back-link" href="/">
          ← Back to home
        </a>
      </div>
      <section className="auth-card">
        <div className="auth-icon" aria-hidden="true">
          GH
        </div>
        <span className="section-kicker">Developer access</span>
        <h1>Continue to CodeΔ</h1>
        <p className="auth-intro">
          Sign in with GitHub to view verification runs for repositories where
          CodeΔ is installed.
        </p>
        <div className="preview-notice">
          <span aria-hidden="true">i</span>
          This preview demonstrates the sign-in flow. It does not request GitHub permissions.
        </div>
        <a className="button button-primary button-full" href="/onboarding">
          <span className="github-button-mark" aria-hidden="true">
            GH
          </span>
          Preview GitHub sign-in
        </a>
        <div className="auth-divider">
          <span />
          <em>or</em>
          <span />
        </div>
        <a className="button button-quiet button-full" href="/runs">
          Enter demo workspace
        </a>
        <p className="auth-fineprint">
          GitHub identity and repository installation are separate. CodeΔ only
          receives access to repositories you explicitly select.
        </p>
      </section>
      <p className="auth-footer">Protected access will be enforced by secure server-side sessions.</p>
    </main>
  );
}

function OnboardingPage() {
  return (
    <main className="onboarding-page">
      <header className="onboarding-header">
        <Wordmark />
        <span className="setup-progress">Setup · 2 of 3</span>
      </header>
      <section className="onboarding-content">
        <div className="onboarding-copy">
          <span className="section-kicker">Connect a repository</span>
          <h1>Bring CodeΔ into your pull requests.</h1>
          <p>
            Install the GitHub App on the repositories you want verified.
            CodeΔ will run automatically when a pull request opens or updates.
          </p>
        </div>
        <div className="setup-grid">
          <article className="setup-step complete">
            <span className="step-icon">✓</span>
            <div>
              <small>Step 1</small>
              <h2>GitHub identity</h2>
              <p>Connected as amansriven</p>
            </div>
            <span className="step-state">Complete</span>
          </article>
          <article className="setup-step current">
            <span className="step-icon">02</span>
            <div>
              <small>Step 2</small>
              <h2>Install CodeΔ</h2>
              <p>Choose an account and the repositories CodeΔ can access.</p>
              <button className="button button-primary" type="button" disabled>
                GitHub App connection coming next
              </button>
            </div>
            <span className="step-state">Current</span>
          </article>
          <article className="setup-step">
            <span className="step-icon">03</span>
            <div>
              <small>Step 3</small>
              <h2>Verify access</h2>
              <p>We’ll confirm your installation and start listening for PR events.</p>
            </div>
            <span className="step-state">Next</span>
          </article>
        </div>
        <div className="onboarding-actions">
          <a className="button button-primary" href="/runs">
            Continue with demo workspace →
          </a>
          <a className="text-link" href={githubLoginUrl}>
            Use another account
          </a>
        </div>
      </section>
    </main>
  );
}

function DashboardSummary({ runs }: { runs: RunSummary[] }) {
  const completed = runs.filter((run) => run.status === "done");
  const regressions = runs.filter((run) => run.highest_severity === "regression");
  const active = runs.filter((run) => run.status === "running" || run.status === "pending");
  return (
    <div className="summary-grid">
      <article>
        <span>PRs verified</span>
        <strong>{completed.length}</strong>
        <small>in this preview</small>
      </article>
      <article>
        <span>Regressions reproduced</span>
        <strong className="summary-danger">{regressions.length}</strong>
        <small>with request evidence</small>
      </article>
      <article>
        <span>Runs in progress</span>
        <strong className="summary-running">{active.length}</strong>
        <small>queued or executing</small>
      </article>
    </div>
  );
}

function RunVerdict({ run }: { run: RunSummary }) {
  if (run.status === "pending" || run.status === "running") {
    return <span className="verdict-muted">Awaiting result</span>;
  }
  if (run.status === "failed") {
    return <span className="verdict-danger">Run failed</span>;
  }
  if (run.finding_count === 0 || run.highest_severity === "none") {
    return <span className="verdict-safe">No changes found</span>;
  }
  if (run.highest_severity === "regression") {
    return (
      <span className="verdict-danger">
        {run.finding_count ?? "—"} regression{run.finding_count === 1 ? "" : "s"}
      </span>
    );
  }
  if (run.highest_severity === "status_code_changed") {
    return <span className="verdict-warning">{run.finding_count ?? "—"} behavior change</span>;
  }
  return <span className="verdict-muted">View result</span>;
}

function RunsTable({ runs }: { runs: RunSummary[] }) {
  if (runs.length === 0) {
    return (
      <div className="empty-state">
        <span className="empty-icon" aria-hidden="true">
          Δ
        </span>
        <h2>No runs match this view</h2>
        <p>Try clearing your search or choosing a different status.</p>
      </div>
    );
  }
  return (
    <div className="runs-table-wrap">
      <table className="runs-table">
        <thead>
          <tr>
            <th>Repository</th>
            <th>Pull request</th>
            <th>Status</th>
            <th>Verdict</th>
            <th>Started</th>
            <th>
              <span className="sr-only">Open run</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const repo = repoParts(run.repo);
            return (
              <tr key={run.id}>
                <td data-label="Repository">
                  <a className="repo-cell" href={`/runs/${run.id}`}>
                    <span className="repo-mark" aria-hidden="true">
                      {repo.name.slice(0, 2).toUpperCase()}
                    </span>
                    <span>
                      <strong>{repo.name}</strong>
                      <small>{repo.owner}</small>
                    </span>
                  </a>
                </td>
                <td data-label="Pull request">
                  {run.pr_number ? (
                    <a
                      className="pr-link"
                      href={`https://github.com/${run.repo}/pull/${run.pr_number}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      #{run.pr_number} <span aria-hidden="true">↗</span>
                    </a>
                  ) : (
                    "Manual run"
                  )}
                </td>
                <td data-label="Status">
                  <StatusBadge status={run.status} />
                </td>
                <td data-label="Verdict">
                  <RunVerdict run={run} />
                </td>
                <td data-label="Started">
                  <time dateTime={run.created_at} title={new Date(run.created_at).toLocaleString()}>
                    {formatRelativeDate(run.created_at)}
                  </time>
                </td>
                <td className="row-action">
                  <a href={`/runs/${run.id}`} aria-label={`Open run ${run.id}`}>
                    →
                  </a>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[]>(demoRuns);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | RunStatus>("all");
  const [loading, setLoading] = useState(Boolean(liveApiUrl));
  const [error, setError] = useState("");

  useEffect(() => {
    if (!liveApiUrl) return;
    const controller = new AbortController();
    fetchRuns(controller.signal)
      .then((data) => {
        setRuns(data);
        setError("");
      })
      .catch((reason: Error) => {
        if (reason.name !== "AbortError") {
          setRuns([]);
          setError(reason.message || "CodeΔ could not reach the runs API. Check the backend connection and try again.");
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  const visibleRuns = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return runs.filter((run) => {
      const matchesQuery =
        !normalized ||
        run.repo.toLowerCase().includes(normalized) ||
        String(run.pr_number ?? "").includes(normalized);
      return matchesQuery && (status === "all" || run.status === status);
    });
  }, [query, runs, status]);

  return (
    <main className="dashboard-page">
      <AppHeader active="runs" />
      <div className="dashboard-content">
        <div className="page-heading">
          <div>
            <span className="section-kicker">Verification activity</span>
            <h1>Runs</h1>
            <p>Concrete API behavior observed across your pull requests.</p>
          </div>
          <a className="button button-quiet" href="/settings/integrations">
            Manage repositories
          </a>
        </div>
        {!liveApiUrl && (
          <div className="demo-banner">
            <span className="demo-banner-icon" aria-hidden="true">
              ◇
            </span>
            <div>
              <strong>You’re exploring a product preview.</strong>
              <p>These runs use representative data shaped exactly like the current CodeΔ API.</p>
            </div>
          </div>
        )}
        <DashboardSummary runs={runs} />
        <section className="runs-panel" aria-labelledby="recent-runs-title">
          <div className="runs-panel-header">
            <div>
              <h2 id="recent-runs-title">Recent runs</h2>
              <span>{visibleRuns.length} shown</span>
            </div>
            <div className="filters">
              <label className="search-field">
                <span className="sr-only">Search runs</span>
                <span aria-hidden="true">⌕</span>
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search repository or PR"
                />
              </label>
              <label className="select-field">
                <span className="sr-only">Filter by status</span>
                <select
                  value={status}
                  onChange={(event) => setStatus(event.target.value as "all" | RunStatus)}
                >
                  <option value="all">All statuses</option>
                  <option value="pending">Queued</option>
                  <option value="running">Running</option>
                  <option value="done">Complete</option>
                  <option value="failed">Failed</option>
                </select>
              </label>
            </div>
          </div>
          {error ? (
            <div className="error-state" role="alert">
              <span aria-hidden="true">!</span>
              <div>
                <h2>{error.includes("Sign in") ? "Sign in required" : "Runs are temporarily unavailable"}</h2>
                <p>{error}</p>
                {error.includes("Sign in") && (
                  <a className="button button-primary" href={githubLoginUrl}>
                    Continue with GitHub
                  </a>
                )}
              </div>
            </div>
          ) : loading ? (
            <div className="loading-state" role="status">
              <span className="loading-spinner" aria-hidden="true" />
              Loading verification runs…
            </div>
          ) : (
            <RunsTable runs={visibleRuns} />
          )}
        </section>
      </div>
    </main>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  if (typeof value === "undefined") {
    return <code className="json-block json-empty">No request body</code>;
  }
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>;
}

function ResponsePanel({
  label,
  branch,
  response,
  tone,
}: {
  label: string;
  branch: string;
  response: Finding["base_response"];
  tone: "base" | "pr";
}) {
  const successful = response.status_code >= 200 && response.status_code < 300;
  return (
    <section className={`response-panel response-panel-${tone}`}>
      <div className="response-panel-header">
        <div>
          <span>{label}</span>
          <code>{branch}</code>
        </div>
        <strong className={successful ? "code-success" : "code-danger"}>
          {response.status_code}
        </strong>
      </div>
      <JsonBlock value={response.body} />
    </section>
  );
}

function FindingCard({
  finding,
  index,
  baseRef,
  headRef,
}: {
  finding: Finding;
  index: number;
  baseRef: string;
  headRef: string;
}) {
  return (
    <article className={`finding-card finding-${finding.kind}`}>
      <div className="finding-card-header">
        <div>
          <span className="finding-index">Finding {String(index + 1).padStart(2, "0")}</span>
          <h2>{finding.case.replaceAll("_", " ")}</h2>
        </div>
        <SeverityBadge kind={finding.kind} />
      </div>
      <div className="request-panel">
        <div className="request-panel-title">
          <span>Reproduced request</span>
          <div className="request-line">
            <span className={`method method-${finding.request.method.toLowerCase()}`}>
              {finding.request.method}
            </span>
            <code>{finding.request.path}</code>
          </div>
        </div>
        <JsonBlock value={finding.request.json} />
      </div>
      <div className="response-comparison">
        <ResponsePanel
          label="Base response"
          branch={baseRef}
          response={finding.base_response}
          tone="base"
        />
        <div className="comparison-divider" aria-hidden="true">
          <span>→</span>
        </div>
        <ResponsePanel
          label="PR response"
          branch={headRef}
          response={finding.pr_response}
          tone="pr"
        />
      </div>
    </article>
  );
}

function RunState({ run }: { run: RunDetail }) {
  if (run.status === "pending" || run.status === "running") {
    return (
      <div className="run-progress-state">
        <span className="run-progress-visual" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="section-kicker">{run.status === "pending" ? "Queued" : "Running now"}</span>
        <h2>{run.status === "pending" ? "Waiting for an available worker" : "Comparing both API versions"}</h2>
        <p>
          CodeΔ is generating changed-endpoint cases and running the same
          requests against the base and PR branches. This page refreshes automatically.
        </p>
      </div>
    );
  }
  if (run.status === "failed") {
    return (
      <div className="error-state detail-error" role="alert">
        <span aria-hidden="true">!</span>
        <div>
          <h2>This verification run failed</h2>
          <p>{run.error || "The backend did not provide an error message."}</p>
        </div>
      </div>
    );
  }
  if (run.result && run.result.findings.length === 0) {
    return (
      <div className="clean-state">
        <span aria-hidden="true">✓</span>
        <h2>No behavioral differences reproduced</h2>
        <p>The generated edge-case requests returned equivalent status codes on both branches.</p>
      </div>
    );
  }
  return null;
}

function RunDetailPage({ runId }: { runId: number }) {
  const fallback = demoDetails[runId];
  const [run, setRun] = useState<RunDetail | undefined>(fallback);
  const [loading, setLoading] = useState(Boolean(liveApiUrl));
  const [error, setError] = useState("");

  useEffect(() => {
    if (!liveApiUrl || !Number.isFinite(runId)) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    const load = async () => {
      try {
        const data = await fetchRun(runId, controller.signal);
        if (!active) return;
        setRun(data);
        setError("");
        setLoading(false);
        if (data.status === "pending" || data.status === "running") {
          timer = setTimeout(load, 3500);
        }
      } catch (reason) {
        if (!active || (reason instanceof Error && reason.name === "AbortError")) return;
        setError(reason instanceof Error ? reason.message : "The run could not be loaded.");
        setLoading(false);
      }
    };
    load();
    return () => {
      active = false;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [runId]);

  if (loading) {
    return (
      <main className="dashboard-page">
        <AppHeader active="runs" />
        <div className="detail-loading" role="status">
          <span className="loading-spinner" aria-hidden="true" />
          Loading run evidence…
        </div>
      </main>
    );
  }

  if (error || !run) {
    return (
      <main className="dashboard-page">
        <AppHeader active="runs" />
        <div className="not-found-state">
          <span aria-hidden="true">404</span>
          <h1>Run not found</h1>
          <p>{error || "This preview does not include the requested run."}</p>
          <a className="button button-primary" href="/runs">
            Back to runs
          </a>
        </div>
      </main>
    );
  }

  const findings = run.result?.findings ?? [];
  const regressions = findings.filter((finding) => finding.kind === "regression").length;
  const repo = repoParts(run.repo);
  return (
    <main className="dashboard-page">
      <AppHeader active="runs" />
      <div className="detail-content">
        <a className="back-link detail-back" href="/runs">
          ← All runs
        </a>
        <section className="run-overview">
          <div className="run-title">
            <div className="repo-mark repo-mark-large" aria-hidden="true">
              {repo.name.slice(0, 2).toUpperCase()}
            </div>
            <div>
              <span className="section-kicker">{repo.owner}</span>
              <h1>{repo.name}</h1>
              <div className="run-subtitle">
                <span>Run #{run.id}</span>
                <span>·</span>
                <a
                  href={`https://github.com/${run.repo}/pull/${run.pr_number}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Pull request #{run.pr_number} ↗
                </a>
              </div>
            </div>
          </div>
          <StatusBadge status={run.status} />
        </section>
        <section
          className={`verdict-card ${
            regressions > 0 ? "verdict-card-danger" : findings.length ? "verdict-card-warning" : "verdict-card-safe"
          }`}
        >
          <div className="verdict-icon" aria-hidden="true">
            {regressions > 0 ? "!" : findings.length ? "↕" : "✓"}
          </div>
          <div>
            <span>Verification verdict</span>
            <h2>
              {run.status !== "done"
                ? "Verification in progress"
                : regressions > 0
                  ? `${regressions} regression reproduced`
                  : findings.length
                    ? `${findings.length} behavior change observed`
                    : "No behavior changes reproduced"}
            </h2>
            <p>
              {regressions > 0
                ? "A request that succeeded on the base branch failed on this pull request."
                : findings.length
                  ? "At least one request returned a different status code between branches."
                  : "The tested edge cases behaved consistently across both branches."}
            </p>
          </div>
          <div className="run-meta">
            <span>
              Base
              <code>{run.base_ref || "base"}</code>
              <small>{run.base_sha || "—"}</small>
            </span>
            <i aria-hidden="true">→</i>
            <span>
              Pull request
              <code>{run.head_ref || "head"}</code>
              <small>{run.head_sha || "—"}</small>
            </span>
          </div>
        </section>
        <RunState run={run} />
        {findings.length > 0 && (
          <section className="findings-section" aria-labelledby="findings-title">
            <div className="findings-heading">
              <div>
                <span className="section-kicker">Request evidence</span>
                <h2 id="findings-title">
                  {findings.length} reproduced {findings.length === 1 ? "difference" : "differences"}
                </h2>
              </div>
              <p>Same request. Two branches. Observable result.</p>
            </div>
            <div className="findings-list">
              {findings.map((finding, index) => (
                <FindingCard
                  key={`${finding.case}-${index}`}
                  finding={finding}
                  index={index}
                  baseRef={run.base_ref || "base"}
                  headRef={run.head_ref || "head"}
                />
              ))}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}

function IntegrationsPage() {
  return (
    <main className="dashboard-page">
      <AppHeader active="settings" />
      <div className="dashboard-content settings-content">
        <div className="page-heading">
          <div>
            <span className="section-kicker">Workspace settings</span>
            <h1>Integrations</h1>
            <p>Manage the identity and repository access CodeΔ uses.</p>
          </div>
        </div>
        <div className="settings-grid">
          <section className="integration-card">
            <div className="integration-logo" aria-hidden="true">
              GH
            </div>
            <div className="integration-main">
              <div>
                <span className="integration-state preview">
                  <i /> Preview identity
                </span>
                <h2>GitHub account</h2>
                <p>OAuth will identify the person accessing this dashboard.</p>
              </div>
              <div className="identity-row">
                <span className="avatar">AS</span>
                <span>
                  <strong>amansriven</strong>
                  <small>Demo workspace owner</small>
                </span>
              </div>
            </div>
          </section>
          <section className="integration-card">
            <div className="integration-logo delta-logo" aria-hidden="true">
              Δ
            </div>
            <div className="integration-main">
              <div>
                <span className="integration-state pending">
                  <i /> Backend connection required
                </span>
                <h2>CodeΔ GitHub App</h2>
                <p>The app receives PR events and publishes check-run evidence.</p>
              </div>
              <div className="repository-list">
                <span>
                  <i>CD</i>
                  amansriven/codedelta-demo-app
                </span>
                <span>
                  <i>IA</i>
                  amansriven/inventory-api
                </span>
                <span>
                  <i>+1</i>
                  1 more preview repository
                </span>
              </div>
            </div>
          </section>
        </div>
        <section className="security-note">
          <span aria-hidden="true">⌾</span>
          <div>
            <h2>Secure launch boundary</h2>
            <p>
              Before public deployment, the FastAPI backend needs OAuth callbacks,
              HTTP-only sessions, and repository-level authorization. The interface
              is ready for those endpoints without simulating security in the browser.
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}

export default function CodeDeltaApp({ route }: { route: string[] }) {
  const path = route.join("/");
  if (!path) return <LandingPage />;
  if (path === "login") return <LoginPage />;
  if (path === "onboarding") return <OnboardingPage />;
  if (path === "runs") return <RunsPage />;
  if (path.startsWith("runs/")) {
    return <RunDetailPage runId={Number(path.split("/")[1])} />;
  }
  if (path === "settings/integrations") return <IntegrationsPage />;
  return (
    <main className="not-found-state standalone">
      <Wordmark />
      <span aria-hidden="true">404</span>
      <h1>That page isn’t part of CodeΔ.</h1>
      <p>The route may have moved or never existed.</p>
      <a className="button button-primary" href="/">
        Return home
      </a>
    </main>
  );
}
