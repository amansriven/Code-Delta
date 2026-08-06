import {
  ContainerProxy,
  getSandbox,
  Sandbox as BaseSandbox,
} from "@cloudflare/sandbox";

import {
  normalizePath,
  parseExecutionRequest,
  redactLog,
  shellQuote,
  type SandboxFile,
} from "./policy.js";

export { ContainerProxy };

export class Sandbox extends BaseSandbox<Env> {
  override enableInternet = false;
  override allowedHosts: string[] = [];
}

type AuthenticatedEnv = Env & { SANDBOX_EXECUTOR_TOKEN: string };

type CheckResult = {
  id: string;
  kind: string;
  status: "passed" | "failed" | "timed_out" | "blocked" | "infrastructure_error";
  command: string;
  exit_code: number | null;
  duration_ms: number;
  stdout: string;
  stderr: string;
};

async function secureEqual(provided: string, expected: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  const left = new Uint8Array(providedHash);
  const right = new Uint8Array(expectedHash);
  let difference = left.length ^ right.length;
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    difference |= (left[index] ?? 0) ^ (right[index] ?? 0);
  }
  return difference === 0;
}

async function readBoundedJson(request: Request, maxBytes: number): Promise<unknown> {
  const declared = Number(request.headers.get("content-length"));
  if (!Number.isInteger(declared) || declared < 1 || declared > maxBytes || !request.body) {
    throw new Error("invalid_content_length");
  }
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      throw new Error("request_too_large");
    }
    chunks.push(value);
  }
  const joined = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    joined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return JSON.parse(new TextDecoder().decode(joined));
}

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function digest(bytes: Uint8Array): Promise<string> {
  const result = await crypto.subtle.digest("SHA-256", bytes.slice().buffer);
  return Array.from(new Uint8Array(result), (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

function byteStream(bytes: Uint8Array): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
}

async function writeFiles(sandbox: Sandbox, files: SandboxFile[]): Promise<void> {
  for (const file of files) {
    const path = normalizePath(file.path);
    const bytes = decodeBase64(file.content_base64);
    if ((await digest(bytes)) !== file.sha256) throw new Error("file_digest_mismatch");
    const slash = path.lastIndexOf("/");
    if (slash > 0) {
      await sandbox.mkdir(`/workspace/repository/${path.slice(0, slash)}`, {
        recursive: true,
      });
    }
    await sandbox.writeFile(`/workspace/repository/${path}`, byteStream(bytes));
  }
}

async function destroyWithTimeout(sandbox: Sandbox): Promise<boolean> {
  try {
    await Promise.race([
      sandbox.destroy(),
      new Promise<never>((_resolve, reject) =>
        setTimeout(() => reject(new Error("destroy_timeout")), 10_000),
      ),
    ]);
    return true;
  } catch {
    return false;
  }
}

async function execute(request: Request, env: AuthenticatedEnv): Promise<Response> {
  const maxBytes = Number(env.MAX_REQUEST_BYTES);
  const maxTimeoutMs = Number(env.MAX_COMMAND_TIMEOUT_MS);
  const payload = parseExecutionRequest(await readBoundedJson(request, maxBytes), maxTimeoutMs);
  const sandbox = getSandbox(
    env.Sandbox,
    `attempt-${payload.attempt_id}-${crypto.randomUUID()}`,
    {
      enableDefaultSession: false,
      normalizeId: true,
      transport: "rpc",
    },
  );
  const started = Date.now();
  const checks: CheckResult[] = [];
  let status: "passed" | "failed" | "blocked" | "infrastructure_error" = "passed";
  let destroyed = false;
  let checkIndex = 0;
  try {
    await sandbox.mkdir("/workspace/repository", { recursive: true });
    await writeFiles(sandbox, payload.files);
    await writeFiles(sandbox, payload.edits);
    for (; checkIndex < payload.checks.length; checkIndex += 1) {
      const check = payload.checks[checkIndex];
      if (!check) throw new Error("invalid_check_index");
      const command = check.argv.map(shellQuote).join(" ");
      try {
        const result = await sandbox.exec(command, {
          cwd: "/workspace/repository",
          timeout: check.timeout_ms,
          env: { CI: "true", HOME: "/tmp/delta-code-home" },
        });
        const checkStatus = result.success ? "passed" : "failed";
        checks.push({
          id: check.id,
          kind: check.kind,
          status: checkStatus,
          command: check.argv.join(" "),
          exit_code: result.exitCode,
          duration_ms: result.duration,
          stdout: redactLog(result.stdout),
          stderr: redactLog(result.stderr),
        });
        if (!result.success) {
          status = "failed";
          checkIndex += 1;
          break;
        }
      } catch (error) {
        const timedOut = error instanceof Error && /timeout/i.test(error.message);
        checks.push({
          id: check.id,
          kind: check.kind,
          status: timedOut ? "timed_out" : "infrastructure_error",
          command: check.argv.join(" "),
          exit_code: null,
          duration_ms: check.timeout_ms,
          stdout: "",
          stderr: timedOut ? "Command exceeded its time limit." : "Sandbox command failed.",
        });
        status = "infrastructure_error";
        checkIndex += 1;
        break;
      }
    }
  } catch {
    status = "infrastructure_error";
  } finally {
    destroyed = await destroyWithTimeout(sandbox);
    if (!destroyed) status = "infrastructure_error";
  }
  for (; checkIndex < payload.checks.length; checkIndex += 1) {
    const check = payload.checks[checkIndex];
    if (!check) continue;
    checks.push({
      id: check.id,
      kind: check.kind,
      status: "blocked",
      command: check.argv.join(" "),
      exit_code: null,
      duration_ms: 0,
      stdout: "",
      stderr: "Not run because an earlier sandbox step did not pass.",
    });
  }
  return Response.json({
    schema_version: "1.0",
    attempt_id: payload.attempt_id,
    status,
    checks,
    executor: { id: "cloudflare-sandbox", version: "0.12.4" },
    duration_ms: Date.now() - started,
    network_policy: "deny_all",
    destroyed,
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json({ status: "ok", execution_enabled: true });
    }
    if (request.method !== "POST" || url.pathname !== "/v1/execute") {
      return Response.json({ error: "not_found" }, { status: 404 });
    }
    const authenticatedEnv = env as AuthenticatedEnv;
    const authorization = request.headers.get("authorization") ?? "";
    const expected = `Bearer ${authenticatedEnv.SANDBOX_EXECUTOR_TOKEN ?? ""}`;
    if (!authenticatedEnv.SANDBOX_EXECUTOR_TOKEN || !(await secureEqual(authorization, expected))) {
      return Response.json({ error: "unauthorized" }, { status: 401 });
    }
    try {
      return await execute(request, authenticatedEnv);
    } catch (error) {
      console.error(
        JSON.stringify({
          message: "sandbox request rejected",
          code: error instanceof SyntaxError ? "invalid_json" : "invalid_request",
          path: url.pathname,
        }),
      );
      return Response.json({ error: "invalid_request" }, { status: 400 });
    }
  },
} satisfies ExportedHandler<Env>;
