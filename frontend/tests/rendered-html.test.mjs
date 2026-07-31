import assert from "node:assert/strict";
import test from "node:test";

const templateRoot = new URL("../", import.meta.url);

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}-${path}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${path}`, {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the Delta Code landing page", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Delta Code — Ship API changes without the guesswork<\/title>/i);
  assert.match(html, /Ship API changes/);
  assert.match(html, /without the guesswork/);
  assert.match(html, /Everything you need to review API behavior/);
  assert.doesNotMatch(html, /codex-preview/);
  assert.doesNotMatch(html, /react-loading-skeleton/);
});

test("server-renders the expanded public product site", async () => {
  const responses = await Promise.all([
    render("/product"),
    render("/how-it-works"),
    render("/docs"),
    render("/security"),
  ]);
  responses.forEach((response) => assert.equal(response.status, 200));

  const [product, workflow, docs, security] = await Promise.all(
    responses.map((response) => response.text()),
  );
  assert.match(product, /API regression testing your whole team can trust/);
  assert.match(workflow, /A rigorous test loop/);
  assert.match(docs, /Local quickstart/);
  assert.match(security, /Least-privilege repository access/);
});

test("server-renders dashboard, run-detail, and settings routes", async () => {
  const [runsResponse, detailResponse, settingsResponse] = await Promise.all([
    render("/runs"),
    render("/runs/14"),
    render("/settings/integrations"),
  ]);
  assert.equal(runsResponse.status, 200);
  assert.equal(detailResponse.status, 200);
  assert.equal(settingsResponse.status, 200);

  const [runs, detail, settings] = await Promise.all([
    runsResponse.text(),
    detailResponse.text(),
    settingsResponse.text(),
  ]);
  assert.match(runs, /Recent runs/);
  assert.match(runs, /By repo/);
  assert.match(runs, /Loading verification runs|You’re exploring a product preview/);
  assert.match(detail, /Loading run evidence|Verification verdict/);
  assert.match(settings, /Settings sections/);
  assert.match(settings, /Repositories/);
  assert.match(settings, /Loading settings|Sign in required/);
});

test("starter preview implementation is removed", async () => {
  const { access, readFile } = await import("node:fs/promises");
  await assert.rejects(access(new URL("../app/_sites-preview", templateRoot)));

  const packageJson = await readFile(new URL("../package.json", import.meta.url), "utf8");
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
});
