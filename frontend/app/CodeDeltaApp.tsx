"use client";

/* eslint-disable @next/next/no-html-link-for-pages -- Vinext's Next Link shim causes duplicate-React hydration failures in local development. */
import Image from "next/image";
import { useEffect, useMemo, useRef, useState } from "react";
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
  retryRun,
  signOut,
} from "./lib/data";

const PRODUCT_NAME = "Code Delta";
const GITHUB_INSTALL_URL = "https://github.com/apps/codedeltaapp/installations/new";

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
        <a className="nav-link" href="/product">
          Product
        </a>
        <a className="nav-link" href="/how-it-works">
          Workflow
        </a>
        <a className="nav-link" href="/docs">
          Docs
        </a>
        <a className="nav-link" href="/security">
          Security
        </a>
        <a className="nav-signin" href={githubLoginUrl}>
          Sign in
        </a>
        <a className="button button-primary button-small" href={githubLoginUrl}>
          Get started <span aria-hidden="true">↗</span>
        </a>
      </nav>
    </header>
  );
}

function PublicFooter() {
  return (
    <footer className="public-footer public-footer-expanded">
      <div className="footer-brand">
        <Wordmark compact />
        <p>Evidence-first API verification for every pull request.</p>
        <span>Built for teams that ship APIs with confidence.</span>
      </div>
      <div className="footer-links">
        <div>
          <strong>Product</strong>
          <a href="/product">Overview</a>
          <a href="/how-it-works">How it works</a>
          <a href="/security">Security</a>
        </div>
        <div>
          <strong>Resources</strong>
          <a href="/docs">Documentation</a>
          <a href="/runs">Live dashboard</a>
          <a href="https://github.com/amansriven/Code-Delta" target="_blank" rel="noreferrer">
            GitHub ↗
          </a>
        </div>
      </div>
      <div className="footer-bottom">
        <span>© 2026 Code Delta</span>
        <span className="system-status"><i /> All systems operational</span>
      </div>
    </footer>
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
              {user?.avatar_url ? (
                <Image src={user.avatar_url} alt="" width={32} height={32} />
              ) : (
                initials
              )}
            </button>
            {menuOpen && (
              <div className="account-dropdown" role="menu">
                <span className="account-dropdown-name">
                  {user ? user.login : "Not signed in"}
                </span>
                {user ? (
                  <>
                    <a role="menuitem" href="/settings/account">
                      Account settings
                    </a>
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
                  </>
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

function ExperienceShell({ children }: { children: React.ReactNode }) {
  const shellRef = useRef<HTMLDivElement>(null);

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const x = (event.clientX / window.innerWidth) * 100;
    const y = (event.clientY / window.innerHeight) * 100;
    shellRef.current?.style.setProperty("--experience-x", `${x}%`);
    shellRef.current?.style.setProperty("--experience-y", `${y}%`);
  }

  return (
    <div
      ref={shellRef}
      className="experience-shell"
      onPointerMove={handlePointerMove}
      onPointerLeave={() => {
        shellRef.current?.style.setProperty("--experience-x", "76%");
        shellRef.current?.style.setProperty("--experience-y", "18%");
      }}
    >
      <div className="experience-backdrop" aria-hidden="true">
        <span className="experience-spotlight" />
        <span className="experience-orb experience-orb-one" />
        <span className="experience-orb experience-orb-two" />
        <span className="experience-orb experience-orb-three" />
        <span className="experience-grid" />
        <span className="data-lane data-lane-one"><i /></span>
        <span className="data-lane data-lane-two"><i /></span>
        <span className="data-lane data-lane-three"><i /></span>
      </div>
      <div className="experience-content">{children}</div>
    </div>
  );
}

function InteractiveLandingShell({ children }: { children: React.ReactNode }) {
  const shellRef = useRef<HTMLDivElement>(null);

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - bounds.left) / bounds.width) * 100;
    const y = ((event.clientY - bounds.top) / bounds.height) * 100;
    shellRef.current?.style.setProperty("--pointer-x", `${x}%`);
    shellRef.current?.style.setProperty("--pointer-y", `${y}%`);
  }

  return (
    <div
      ref={shellRef}
      className="landing-shell"
      onPointerMove={handlePointerMove}
      onPointerLeave={() => {
        shellRef.current?.style.setProperty("--pointer-x", "72%");
        shellRef.current?.style.setProperty("--pointer-y", "24%");
      }}
    >
      <div className="cursor-aura" aria-hidden="true" />
      <div className="aurora aurora-a" aria-hidden="true" />
      <div className="aurora aurora-b" aria-hidden="true" />
      <div className="mesh-grid" aria-hidden="true" />
      <div className="constellation" aria-hidden="true">
        <i /><i /><i /><i /><i /><i />
        <span /><span /><span />
      </div>
      {children}
    </div>
  );
}

function EvidencePreview() {
  const scenarios = [
    {
      label: "Required field",
      title: "PR #128 · verification",
      state: "Regression",
      kind: "regression" as const,
      caseName: "omit_discount",
      method: "POST",
      path: "/items",
      baseStatus: "201",
      baseBody: '{ "discount": 0.0 }',
      prStatus: "422",
      prBody: '{ "detail": "Field required" }',
    },
    {
      label: "Status drift",
      title: "PR #204 · verification",
      state: "Behavior changed",
      kind: "status_code_changed" as const,
      caseName: "unknown_user",
      method: "GET",
      path: "/users/unknown",
      baseStatus: "404",
      baseBody: '{ "detail": "Not found" }',
      prStatus: "200",
      prBody: '{ "id": null }',
    },
    {
      label: "Safe change",
      title: "PR #219 · verification",
      state: "No regression",
      kind: "safe" as const,
      caseName: "health_contract",
      method: "GET",
      path: "/health",
      baseStatus: "200",
      baseBody: '{ "status": "ok" }',
      prStatus: "200",
      prBody: '{ "status": "ok" }',
    },
  ];
  const [activeScenario, setActiveScenario] = useState(0);
  const scenario = scenarios[activeScenario];

  return (
    <div className="evidence-window" aria-label="Interactive API behavior comparison">
      <div className="window-bar">
        <span className="window-lights" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span>{scenario.title}</span>
        <span className={`verified-label verified-${scenario.kind}`}>{scenario.state}</span>
      </div>
      <div className="evidence-content">
        <div className="finding-heading">
          {scenario.kind === "safe" ? (
            <span className="severity-badge severity-safe"><span>✓</span>No regression</span>
          ) : (
            <SeverityBadge kind={scenario.kind} />
          )}
          <span className="case-name">{scenario.caseName}</span>
        </div>
        <div className="request-line">
          <span className={`method method-${scenario.method.toLowerCase()}`}>{scenario.method}</span>
          <code>{scenario.path}</code>
        </div>
        <div className="preview-compare">
          <div className="response-preview response-base">
            <div>
              <span>BASE</span>
              <strong className={scenario.baseStatus.startsWith("2") ? "code-success" : "code-danger"}>
                {scenario.baseStatus}
              </strong>
            </div>
            <code>{scenario.baseBody}</code>
          </div>
          <div className="compare-arrow" aria-hidden="true">
            →
          </div>
          <div className="response-preview response-pr">
            <div>
              <span>PR</span>
              <strong className={scenario.prStatus === scenario.baseStatus ? "code-success" : "code-danger"}>
                {scenario.prStatus}
              </strong>
            </div>
            <code>{scenario.prBody}</code>
          </div>
        </div>
        <div className="scenario-switcher" aria-label="Comparison examples">
          {scenarios.map((item, index) => (
            <button
              key={item.label}
              type="button"
              className={activeScenario === index ? "active" : ""}
              aria-pressed={activeScenario === index}
              onClick={() => setActiveScenario(index)}
            >
              <i aria-hidden="true" />
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function LandingPage() {
  return (
    <main className="public-page">
      <InteractiveLandingShell>
        <PublicHeader />
        <section className="hero">
          <div className="hero-copy">
            <div className="eyebrow">
              <span />
              GitHub-native API verification
              <b>New</b>
            </div>
            <h1>
              Ship API changes
              <br />
              <em>without the guesswork.</em>
            </h1>
            <p>
              CodeΔ turns every pull request into a real behavioral comparison.
              We generate targeted requests, run both branches, and surface only
              the API changes your team needs to review.
            </p>
            <div className="hero-actions">
              <a className="button button-primary button-large" href={githubLoginUrl}>
                Start verifying with GitHub <span aria-hidden="true">→</span>
              </a>
              <a className="button button-quiet button-large" href="/runs">
                View live dashboard
              </a>
            </div>
            <div className="hero-proof">
              <span><i>✓</i> Reproducible evidence</span>
              <span><i>✓</i> OpenAPI aware</span>
              <span><i>✓</i> Setup in minutes</span>
            </div>
          </div>
          <div className="hero-visual">
            <div className="floating-chip chip-one"><i /> OpenAPI diff detected</div>
            <div className="floating-chip chip-two">✓ Check run published</div>
            <EvidencePreview />
            <div className="visual-glow" aria-hidden="true" />
          </div>
        </section>
        <div className="trusted-strip">
          <span>Designed for modern API teams</span>
          <div>
            <b>FASTAPI</b>
            <b>OPENAPI</b>
            <b>GITHUB</b>
            <b>POSTGRESQL</b>
            <b>PYTHON</b>
          </div>
        </div>
      </InteractiveLandingShell>

      <section className="story-section">
        <div className="section-heading centered-heading">
          <span className="section-kicker">From diff to decision</span>
          <h2>Everything you need to review API behavior.</h2>
          <p>One focused workflow replaces manual reproduction, speculative comments, and scattered logs.</p>
        </div>
        <div className="workflow-rail">
          <article>
            <span className="workflow-icon">⌁</span>
            <small>01 · Detect</small>
            <h3>Understand the changed surface</h3>
            <p>CodeΔ reads both OpenAPI specifications and isolates endpoints, parameters, and fields touched by the PR.</p>
          </article>
          <span className="rail-arrow">→</span>
          <article>
            <span className="workflow-icon">⚡</span>
            <small>02 · Exercise</small>
            <h3>Run targeted edge cases</h3>
            <p>Deterministic and AI-assisted cases execute against both branches with identical requests.</p>
          </article>
          <span className="rail-arrow">→</span>
          <article>
            <span className="workflow-icon">Δ</span>
            <small>03 · Compare</small>
            <h3>Review concrete evidence</h3>
            <p>Only reproduced differences appear in your GitHub Check and dashboard, with both responses attached.</p>
          </article>
        </div>
      </section>

      <section className="bento-section">
        <div className="section-heading">
          <span className="section-kicker">Built for signal</span>
          <h2>A calmer way to ship fast.</h2>
        </div>
        <div className="bento-grid">
          <article className="bento-card bento-wide bento-blue">
            <div>
              <span className="card-label">Behavioral diff</span>
              <h3>See what users experience—not just what code changed.</h3>
              <p>Compare status codes and response bodies from real executions on each side of the pull request.</p>
            </div>
            <div className="mini-diff" aria-hidden="true">
              <span><b>main</b><code>201 Created</code></span>
              <i>→</i>
              <span className="mini-diff-danger"><b>pull request</b><code>422 Required</code></span>
            </div>
          </article>
          <article className="bento-card">
            <span className="card-icon">◎</span>
            <span className="card-label">Repository aware</span>
            <h3>One workspace, every connected repo.</h3>
            <p>Installation-scoped access keeps teams focused on exactly the repositories they manage.</p>
          </article>
          <article className="bento-card">
            <span className="card-icon">↻</span>
            <span className="card-label">Reliable operations</span>
            <h3>Async runs with safe retries.</h3>
            <p>PostgreSQL-backed jobs capture progress, errors, history, and retry state without blocking webhooks.</p>
          </article>
          <article className="bento-card bento-wide ai-card">
            <div>
              <span className="card-label">AI-ready, evidence-first</span>
              <h3>Intelligence that extends tests—never invents verdicts.</h3>
              <p>LLMs can propose semantic edge cases and explain impact, while the regression decision always comes from reproduced requests.</p>
            </div>
            <div className="ai-orbit" aria-hidden="true">
              <span>API</span><i /><i /><i />
            </div>
          </article>
        </div>
      </section>

      <section className="final-cta">
        <div className="cta-orb" aria-hidden="true" />
        <span className="section-kicker">Start with your next pull request</span>
        <h2>Make every API change explain itself.</h2>
        <p>Connect GitHub, select a repository, and let CodeΔ turn hidden behavior changes into reviewable evidence.</p>
        <div>
          <a className="button button-primary button-large" href={githubLoginUrl}>Connect GitHub <span>→</span></a>
          <a className="button button-quiet button-large" href="/docs">Read the docs</a>
        </div>
      </section>
      <PublicFooter />
    </main>
  );
}

function PublicPageHero({
  kicker,
  title,
  description,
  children,
}: {
  kicker: string;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <section className="subpage-hero">
      <span className="section-kicker">{kicker}</span>
      <h1>{title}</h1>
      <p>{description}</p>
      {children}
    </section>
  );
}

function ProductPage() {
  return (
    <main className="public-page light-public-page">
      <PublicHeader />
      <PublicPageHero
        kicker="The verification platform"
        title="API regression testing your whole team can trust."
        description="CodeΔ connects contract changes to runtime evidence, giving reviewers a fast, shared understanding of what a pull request changes for real clients."
      >
        <div className="subpage-actions">
          <a className="button button-primary button-large" href={githubLoginUrl}>Connect a repository →</a>
          <a className="button button-quiet button-large" href="/how-it-works">Explore the workflow</a>
        </div>
      </PublicPageHero>
      <section className="product-showcase">
        <div className="showcase-copy">
          <span className="section-kicker">A complete feedback loop</span>
          <h2>From pull request to proof, automatically.</h2>
          <p>Every run preserves the context a reviewer needs: repository, branch, commit, generated request, both responses, severity, and operational state.</p>
          <ul className="check-list">
            <li><i>✓</i> OpenAPI-aware case generation</li>
            <li><i>✓</i> Real base-versus-head execution</li>
            <li><i>✓</i> GitHub Check Run reporting</li>
            <li><i>✓</i> Searchable, repository-grouped history</li>
          </ul>
        </div>
        <EvidencePreview />
      </section>
      <section className="feature-matrix">
        {[
          ["⌁", "Changed-surface detection", "Targets only endpoints and inputs affected by the pull request."],
          ["◫", "Request provenance", "Stable case IDs and rationales make every generated request traceable."],
          ["Δ", "Behavior classification", "Separates true regressions from other status-code changes."],
          ["↻", "Failure recovery", "Clear errors and one-click retries keep transient failures actionable."],
          ["◎", "Repository visibility", "See every repository granted to the CodeΔ GitHub App."],
          ["✦", "AI enrichment", "Optional semantic cases and explanations layer onto deterministic evidence."],
        ].map(([icon, title, copy]) => (
          <article key={title}>
            <span>{icon}</span><h3>{title}</h3><p>{copy}</p>
          </article>
        ))}
      </section>
      <PublicFooter />
    </main>
  );
}

function WorkflowPage() {
  return (
    <main className="public-page light-public-page">
      <PublicHeader />
      <PublicPageHero
        kicker="How Code Delta works"
        title="A rigorous test loop, triggered by a pull request."
        description="CodeΔ combines contract analysis, isolated execution, and evidence-first reporting in one repeatable workflow."
      />
      <section className="timeline-section">
        {[
          ["01", "A pull request changes your API", "The GitHub App receives the event and creates an asynchronous verification run.", "pull_request.opened"],
          ["02", "CodeΔ maps the changed surface", "Base and head OpenAPI specifications are compared to identify testable request changes.", "openapi.diff()"],
          ["03", "Focused cases are generated", "Rules cover contract boundaries; optional AI adds semantic cases based on field meaning.", "cases.generate()"],
          ["04", "Both branches are exercised", "The same request runs against isolated base and pull-request applications.", "base ⇄ head"],
          ["05", "Only differences survive", "Equivalent behavior and pre-existing failures are suppressed to keep the result focused.", "compare.responses()"],
          ["06", "Evidence reaches the review", "Findings are stored, published as a GitHub Check, and available in the dashboard.", "check_run.complete"],
        ].map(([number, title, copy, code]) => (
          <article key={number}>
            <span className="timeline-number">{number}</span>
            <div><h2>{title}</h2><p>{copy}</p></div>
            <code>{code}</code>
          </article>
        ))}
      </section>
      <section className="principle-callout">
        <span>Our core principle</span>
        <blockquote>“AI can suggest what to test. Only execution can prove what changed.”</blockquote>
        <p>This boundary keeps CodeΔ useful in serious engineering workflows: generated ideas remain clearly separate from reproduced evidence.</p>
      </section>
      <PublicFooter />
    </main>
  );
}

function DocsPage() {
  return (
    <main className="public-page light-public-page">
      <PublicHeader />
      <div className="docs-layout">
        <aside className="docs-sidebar">
          <span>Documentation</span>
          <a className="active" href="#quickstart">Quickstart</a>
          <a href="#architecture">Architecture</a>
          <a href="#local-development">Local development</a>
          <a href="#api">API reference</a>
          <a href="#ai">AI assistance</a>
        </aside>
        <article className="docs-content">
          <span className="section-kicker">Code Delta docs</span>
          <h1 id="quickstart">Start verifying API behavior.</h1>
          <p className="docs-lede">Get the complete CodeΔ stack running locally, or connect the hosted dashboard to a GitHub App installation.</p>
          <div className="docs-note"><b>Prerequisites</b><span>Python 3.12+, Node.js 22.13+, Docker, Git, and Make.</span></div>
          <h2>Local quickstart</h2>
          <p>Install dependencies and start PostgreSQL:</p>
          <pre><code>{`make setup\nmake db-up\nmake db-schema`}</code></pre>
          <p>Then run the API, worker, and frontend in separate terminals:</p>
          <pre><code>{`make api\nmake worker\nmake frontend-dev LIVE_API_URL=http://localhost:8000`}</code></pre>
          <h2 id="architecture">Architecture</h2>
          <div className="architecture-row">
            <span>GitHub App</span><i>→</i><span>FastAPI</span><i>→</i><span>PostgreSQL queue</span><i>→</i><span>Worker</span><i>→</i><span>Check Run</span>
          </div>
          <h2 id="local-development">Local URLs</h2>
          <table className="docs-table"><tbody>
            <tr><th>Dashboard</th><td><code>http://localhost:3000</code></td></tr>
            <tr><th>Backend API</th><td><code>http://localhost:8000</code></td></tr>
            <tr><th>Interactive API docs</th><td><code>http://localhost:8000/docs</code></td></tr>
            <tr><th>Health endpoint</th><td><code>http://localhost:8000/health</code></td></tr>
          </tbody></table>
          <h2 id="api">Core API</h2>
          <div className="endpoint-list">
            <span><b>GET</b><code>/auth/me</code><small>Current GitHub identity and repositories</small></span>
            <span><b>GET</b><code>/runs</code><small>Recent authorized verification runs</small></span>
            <span><b>GET</b><code>/runs/&#123;id&#125;</code><small>Complete run evidence and branch context</small></span>
            <span><b>POST</b><code>/runs/&#123;id&#125;/retry</code><small>Requeue a verification run</small></span>
          </div>
          <h2 id="ai">AI assistance</h2>
          <p>Set <code>OLLAMA_URL</code> and <code>OLLAMA_MODEL</code> to enable semantic case suggestions and evidence-grounded explanations. CodeΔ continues deterministically when the model is unavailable.</p>
        </article>
      </div>
      <PublicFooter />
    </main>
  );
}

function SecurityPage() {
  return (
    <main className="public-page light-public-page">
      <PublicHeader />
      <PublicPageHero
        kicker="Security by design"
        title="Repository access stays explicit. Evidence stays scoped."
        description="CodeΔ uses separate GitHub App and OAuth responsibilities so repository automation and dashboard identity never blur together."
      />
      <section className="security-grid">
        <article className="security-primary">
          <span className="card-icon">◈</span>
          <h2>Least-privilege repository access</h2>
          <p>CodeΔ can only receive events and read code for repositories explicitly selected during GitHub App installation.</p>
        </article>
        <article><span>01</span><h3>Signed webhooks</h3><p>Every incoming GitHub event is verified before processing.</p></article>
        <article><span>02</span><h3>Server-side sessions</h3><p>Dashboard access uses secure, HTTP-only session cookies.</p></article>
        <article><span>03</span><h3>Scoped run queries</h3><p>Run history and retries are filtered by the signed-in user’s accessible repositories.</p></article>
        <article><span>04</span><h3>Isolated execution</h3><p>Base and head applications run in separate subprocesses during comparison.</p></article>
      </section>
      <section className="security-boundary">
        <div><span className="section-kicker">Clear trust boundaries</span><h2>Automation and identity remain separate.</h2></div>
        <div className="boundary-cards">
          <article><b>GitHub App</b><p>Repository events, installation tokens, code access, and Check Run publishing.</p></article>
          <span>≠</span>
          <article><b>GitHub OAuth</b><p>User sign-in, server-side sessions, and repository-scoped dashboard authorization.</p></article>
        </div>
      </section>
      <PublicFooter />
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
        <small>{liveApiUrl ? "across recent runs" : "in this preview"}</small>
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
  const [view, setView] = useState<"runs" | "repos">("runs");

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

  const groupedRuns = useMemo(() => {
    const groups = new Map<string, RunSummary[]>();
    visibleRuns.forEach((run) => {
      groups.set(run.repo, [...(groups.get(run.repo) ?? []), run]);
    });
    return [...groups.entries()]
      .map(([repo, repoRuns]) => ({
        repo,
        runs: repoRuns,
        regressions: repoRuns.filter((run) => run.highest_severity === "regression").length,
        lastRun: repoRuns.reduce(
          (latest, run) =>
            new Date(run.created_at).getTime() > new Date(latest).getTime()
              ? run.created_at
              : latest,
          repoRuns[0].created_at,
        ),
      }))
      .sort((a, b) => new Date(b.lastRun).getTime() - new Date(a.lastRun).getTime());
  }, [visibleRuns]);

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
              <h2 id="recent-runs-title">{view === "runs" ? "Recent runs" : "Repositories"}</h2>
              <span>{visibleRuns.length} shown</span>
            </div>
            <div className="filters">
              <div className="view-toggle" aria-label="Runs view">
                <button
                  type="button"
                  className={view === "runs" ? "active" : ""}
                  aria-pressed={view === "runs"}
                  onClick={() => setView("runs")}
                >
                  Runs
                </button>
                <button
                  type="button"
                  className={view === "repos" ? "active" : ""}
                  aria-pressed={view === "repos"}
                  onClick={() => setView("repos")}
                >
                  By repo
                </button>
              </div>
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
          ) : view === "repos" ? (
            <RepoGroups groups={groupedRuns} />
          ) : (
            <RunsTable runs={visibleRuns} />
          )}
        </section>
      </div>
    </main>
  );
}

function RepoGroups({
  groups,
}: {
  groups: Array<{
    repo: string;
    runs: RunSummary[];
    regressions: number;
    lastRun: string;
  }>;
}) {
  if (groups.length === 0) {
    return (
      <div className="empty-state">
        <span className="empty-icon" aria-hidden="true">Δ</span>
        <h2>No repositories match this view</h2>
        <p>Try clearing your search or choosing a different status.</p>
      </div>
    );
  }
  return (
    <div className="repo-groups">
      <p className="data-window-note">Based on the 50 most recent runs available.</p>
      {groups.map((group) => {
        const repo = repoParts(group.repo);
        return (
          <section className="repo-group" key={group.repo}>
            <div className="repo-group-header">
              <div className="repo-cell">
                <span className="repo-mark" aria-hidden="true">
                  {repo.name.slice(0, 2).toUpperCase()}
                </span>
                <span>
                  <strong>{repo.name}</strong>
                  <small>{repo.owner}</small>
                </span>
              </div>
              <dl>
                <div><dt>Runs</dt><dd>{group.runs.length}</dd></div>
                <div><dt>Regressions</dt><dd className={group.regressions ? "summary-danger" : ""}>{group.regressions}</dd></div>
                <div>
                  <dt>Last run</dt>
                  <dd title={new Date(group.lastRun).toLocaleString()}>{formatRelativeDate(group.lastRun)}</dd>
                </div>
              </dl>
            </div>
            <RunsTable runs={group.runs} />
          </section>
        );
      })}
    </div>
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
          {run.error ? (
            <details className="traceback" open>
              <summary>Error details</summary>
              <pre>{run.error}</pre>
            </details>
          ) : (
            <p>The backend did not provide an error message.</p>
          )}
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
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

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
  }, [reloadKey, runId]);

  const handleRetry = async () => {
    if (!liveApiUrl) return;
    setRetrying(true);
    setRetryError("");
    try {
      await retryRun(runId);
      setRun((current) =>
        current ? { ...current, status: "pending", result: null, error: undefined } : current,
      );
      setReloadKey((key) => key + 1);
    } catch (reason) {
      setRetryError(reason instanceof Error ? reason.message : "The run could not be retried.");
    } finally {
      setRetrying(false);
    }
  };

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
                {run.pr_number ? (
                  <a
                    href={`https://github.com/${run.repo}/pull/${run.pr_number}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Pull request #{run.pr_number} ↗
                  </a>
                ) : (
                  <span>Manual run</span>
                )}
              </div>
            </div>
          </div>
          <div className="run-actions">
            <StatusBadge status={run.status} />
            {liveApiUrl && (
              <button
                className="button button-quiet button-small"
                type="button"
                disabled={retrying || run.status === "pending" || run.status === "running"}
                onClick={handleRetry}
              >
                {retrying ? "Retrying…" : "Retry run"}
              </button>
            )}
          </div>
        </section>
        {retryError && <p className="action-error" role="alert">{retryError}</p>}
        <section
          className={`verdict-card ${
            run.status === "failed" || regressions > 0
              ? "verdict-card-danger"
              : findings.length
                ? "verdict-card-warning"
                : run.status === "done"
                  ? "verdict-card-safe"
                  : ""
          }`}
        >
          <div className="verdict-icon" aria-hidden="true">
            {run.status === "failed" || regressions > 0
              ? "!"
              : findings.length
                ? "↕"
                : run.status === "done"
                  ? "✓"
                  : "…"}
          </div>
          <div>
            <span>Verification verdict</span>
            <h2>
              {run.status !== "done"
                ? run.status === "failed"
                  ? "Verification failed"
                  : "Verification in progress"
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
              <small title={run.base_sha}>{run.base_sha?.slice(0, 7) || "—"}</small>
            </span>
            <i aria-hidden="true">→</i>
            <span>
              Pull request
              <code>{run.head_ref || "head"}</code>
              <small title={run.head_sha}>{run.head_sha?.slice(0, 7) || "—"}</small>
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

function SettingsPage({ tab }: { tab: "account" | "repositories" }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(Boolean(liveApiUrl));

  useEffect(() => {
    if (!liveApiUrl) return;
    const controller = new AbortController();
    fetchMe(controller.signal)
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  return (
    <main className="dashboard-page">
      <AppHeader active="settings" />
      <div className="dashboard-content settings-content">
        <div className="page-heading">
          <div>
            <span className="section-kicker">Workspace settings</span>
            <h1>Settings</h1>
            <p>Manage the identity and repository access CodeΔ uses.</p>
          </div>
        </div>
        <nav className="settings-tabs" aria-label="Settings sections">
          <a className={tab === "account" ? "active" : ""} href="/settings/account">Account</a>
          <a className={tab === "repositories" ? "active" : ""} href="/settings/integrations">Repositories</a>
        </nav>
        {loading ? (
          <div className="loading-state settings-loading" role="status">
            <span className="loading-spinner" aria-hidden="true" />
            Loading settings…
          </div>
        ) : !user ? (
          <div className="error-state settings-signin">
            <span aria-hidden="true">!</span>
            <div>
              <h2>Sign in required</h2>
              <p>Sign in with GitHub to manage your account and repository access.</p>
              <a className="button button-primary" href={githubLoginUrl}>Continue with GitHub</a>
            </div>
          </div>
        ) : tab === "account" ? (
          <div className="settings-grid">
          <section className="integration-card">
            <div className="integration-logo" aria-hidden="true">
              GH
            </div>
            <div className="integration-main">
              <div>
                <span className="integration-state connected">
                  <i /> Connected
                </span>
                <h2>GitHub account</h2>
                <p>Your GitHub identity controls access to this dashboard.</p>
              </div>
              <div className="identity-row">
                {user.avatar_url ? (
                  <Image
                    className="settings-avatar"
                    src={user.avatar_url}
                    alt=""
                    width={38}
                    height={38}
                  />
                ) : (
                  <span className="avatar">{user.login.slice(0, 2).toUpperCase()}</span>
                )}
                <span>
                  <strong>{user.login}</strong>
                  <a href={`https://github.com/${user.login}`} target="_blank" rel="noreferrer">
                    View GitHub profile ↗
                  </a>
                </span>
              </div>
            </div>
          </section>
          </div>
        ) : (
          <div className="settings-grid">
          <section className="integration-card">
            <div className="integration-logo delta-logo" aria-hidden="true">
              Δ
            </div>
            <div className="integration-main">
              <div>
                <span className="integration-state connected">
                  <i /> {user.accessible_repos.length} connected
                </span>
                <h2>CodeΔ GitHub App</h2>
                <p>The app receives PR events and publishes check-run evidence.</p>
              </div>
              <div className="repository-list">
                {user.accessible_repos.length ? user.accessible_repos.map((repo) => {
                  const parts = repoParts(repo);
                  return (
                    <span key={repo}>
                      <i>{parts.name.slice(0, 2).toUpperCase()}</i>
                      {repo}
                    </span>
                  );
                }) : (
                  <div className="repository-empty">
                    <strong>No repositories connected yet</strong>
                    <small>Choose repositories in the GitHub App installation flow.</small>
                  </div>
                )}
              </div>
            </div>
          </section>
          <section className="install-card">
            <div>
              <h2>Connect more repositories</h2>
              <p>Grant CodeΔ access on GitHub. Newly selected repositories appear here when you return.</p>
            </div>
            <a className="button button-primary" href={GITHUB_INSTALL_URL} target="_blank" rel="noreferrer">
              Install on more repos ↗
            </a>
          </section>
          </div>
        )}
      </div>
    </main>
  );
}

export default function CodeDeltaApp({ route }: { route: string[] }) {
  const path = route.join("/");
  let page: React.ReactNode = null;

  if (!path) page = <LandingPage />;
  else if (path === "product") page = <ProductPage />;
  else if (path === "how-it-works") page = <WorkflowPage />;
  else if (path === "docs") page = <DocsPage />;
  else if (path === "security") page = <SecurityPage />;
  else if (path === "login") page = <LoginPage />;
  else if (path === "onboarding") page = <OnboardingPage />;
  else if (path === "runs") page = <RunsPage />;
  if (path.startsWith("runs/")) {
    page = <RunDetailPage runId={Number(path.split("/")[1])} />;
  } else if (path === "settings" || path === "settings/account") {
    page = <SettingsPage tab="account" />;
  } else if (path === "settings/integrations") {
    page = <SettingsPage tab="repositories" />;
  } else if (!page) {
    page = (
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

  return <ExperienceShell>{page}</ExperienceShell>;
}
