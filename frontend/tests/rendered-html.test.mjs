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

test("server-renders the Code Delta landing page", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>CodeΔ — Evidence, not speculation<\/title>/i);
  assert.match(html, /Your API changed/);
  assert.match(html, /Know exactly how/);
  assert.match(html, /Evidence from real requests/);
  assert.doesNotMatch(html, /codex-preview/);
  assert.doesNotMatch(html, /react-loading-skeleton/);
});

test("server-renders dashboard and run-detail routes", async () => {
  const [runsResponse, detailResponse] = await Promise.all([
    render("/runs"),
    render("/runs/14"),
  ]);
  assert.equal(runsResponse.status, 200);
  assert.equal(detailResponse.status, 200);

  const [runs, detail] = await Promise.all([
    runsResponse.text(),
    detailResponse.text(),
  ]);
  assert.match(runs, /Recent runs/);
  assert.match(runs, /codedelta-demo-app/);
  assert.match(detail, /regression reproduced/i);
  assert.match(detail, /omit discount/i);
  assert.match(detail, /Base response/);
  assert.match(detail, /PR response/);
});

test("starter preview implementation is removed", async () => {
  const { access, readFile } = await import("node:fs/promises");
  await assert.rejects(access(new URL("../app/_sites-preview", templateRoot)));

  const packageJson = await readFile(new URL("../package.json", import.meta.url), "utf8");
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
});
