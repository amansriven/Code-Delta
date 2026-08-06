export const MAX_FILES = 1000;
export const MAX_EDITS = 100;
export const MAX_CHECKS = 10;
export const MAX_LOG_BYTES = 20_000;

const ALLOWED_EXECUTABLES = new Set([
  "python",
  "python3",
  "pytest",
  "ruff",
  "mypy",
  "pyright",
  "pip",
  "uv",
  "poetry",
  "node",
  "npm",
  "npx",
  "pnpm",
  "yarn",
  "bun",
  "go",
  "cargo",
  "bundle",
]);

const DENIED_PREFIXES = [
  ".git",
  ".github/workflows",
  ".circleci",
  ".buildkite",
  ".ssh",
  ".aws",
  ".config/gcloud",
];
const DENIED_FILE_NAMES = new Set([
  ".env",
  ".env.local",
  ".npmrc",
  ".pypirc",
  ".netrc",
  "id_rsa",
  "id_ed25519",
  "credentials",
  "credentials.json",
  "credentials.yml",
  "credentials.yaml",
  "service-account.json",
]);
const SECRET_PATTERNS = [
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/g,
  /\bgh[pousr]_[A-Za-z0-9_]{20,}\b/g,
  /\bgithub_pat_[A-Za-z0-9_]{20,}\b/g,
  /\bsk-[A-Za-z0-9_-]{20,}\b/g,
  /\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*(['"]?)[^'"\s]{8,}\1/gi,
];

export type SandboxFile = { path: string; content_base64: string; sha256: string };
export type VerificationCommand = {
  id: string;
  kind: string;
  argv: string[];
  timeout_ms: number;
};
export type ExecutionRequest = {
  schema_version: "1.0";
  attempt_id: string;
  snapshot_digest: string;
  patch_digest: string;
  files: SandboxFile[];
  edits: SandboxFile[];
  checks: VerificationCommand[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function normalizePath(value: string): string {
  if (!value || value.includes("\\") || value.includes("\0") || value.startsWith("/")) {
    throw new Error("invalid_path");
  }
  const parts = value.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error("invalid_path");
  }
  const normalized = parts.join("/");
  const lowered = normalized.toLowerCase();
  if (
    DENIED_PREFIXES.some(
      (prefix) => lowered === prefix || lowered.startsWith(`${prefix}/`),
    )
  ) {
    throw new Error("denied_path");
  }
  const name = parts.at(-1)?.toLowerCase() ?? "";
  if (
    DENIED_FILE_NAMES.has(name) ||
    name.startsWith(".env.") ||
    [".key", ".pem", ".p12", ".pfx"].some((suffix) => name.endsWith(suffix))
  ) {
    throw new Error("denied_path");
  }
  return normalized;
}

function parseFile(value: unknown): SandboxFile {
  if (!isRecord(value)) throw new Error("invalid_file");
  const path = value.path;
  const content = value.content_base64;
  const sha256 = value.sha256;
  if (
    typeof path !== "string" ||
    typeof content !== "string" ||
    typeof sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(sha256) ||
    !/^[A-Za-z0-9+/]*={0,2}$/.test(content)
  ) {
    throw new Error("invalid_file");
  }
  return { path: normalizePath(path), content_base64: content, sha256 };
}

function parseCommand(value: unknown, maxTimeoutMs: number): VerificationCommand {
  if (!isRecord(value)) throw new Error("invalid_check");
  const { id, kind, argv, timeout_ms: timeoutMs } = value;
  if (
    typeof id !== "string" ||
    !/^[a-z0-9][a-z0-9_-]{0,99}$/.test(id) ||
    typeof kind !== "string" ||
    !Array.isArray(argv) ||
    argv.length < 1 ||
    argv.length > 32 ||
    typeof timeoutMs !== "number" ||
    !Number.isInteger(timeoutMs) ||
    timeoutMs < 100 ||
    timeoutMs > maxTimeoutMs
  ) {
    throw new Error("invalid_check");
  }
  if (!argv.every((argument) => typeof argument === "string")) {
    throw new Error("invalid_check");
  }
  const typedArgv = argv as string[];
  if (
    !ALLOWED_EXECUTABLES.has(typedArgv[0] ?? "") ||
    typedArgv.some(
      (argument) =>
        !argument || argument.length > 500 || /[\0\r\n]/.test(argument),
    )
  ) {
    throw new Error("invalid_check");
  }
  return { id, kind, argv: typedArgv, timeout_ms: timeoutMs };
}

export function parseExecutionRequest(value: unknown, maxTimeoutMs: number): ExecutionRequest {
  if (!isRecord(value)) throw new Error("invalid_request");
  const { schema_version: schemaVersion, attempt_id: attemptId } = value;
  const { snapshot_digest: snapshotDigest, patch_digest: patchDigest } = value;
  if (
    schemaVersion !== "1.0" ||
    typeof attemptId !== "string" ||
    !/^[A-Za-z0-9_-]{1,100}$/.test(attemptId) ||
    typeof snapshotDigest !== "string" ||
    !/^sha256:[a-f0-9]{64}$/.test(snapshotDigest) ||
    typeof patchDigest !== "string" ||
    !/^[a-f0-9]{64}$/.test(patchDigest) ||
    !Array.isArray(value.files) ||
    value.files.length > MAX_FILES ||
    !Array.isArray(value.edits) ||
    value.edits.length < 1 ||
    value.edits.length > MAX_EDITS ||
    !Array.isArray(value.checks) ||
    value.checks.length < 1 ||
    value.checks.length > MAX_CHECKS
  ) {
    throw new Error("invalid_request");
  }
  const files = value.files.map(parseFile);
  const edits = value.edits.map(parseFile);
  const checks = value.checks.map((check) => parseCommand(check, maxTimeoutMs));
  if (new Set(files.map((file) => file.path)).size !== files.length) {
    throw new Error("duplicate_file");
  }
  if (new Set(edits.map((file) => file.path)).size !== edits.length) {
    throw new Error("duplicate_edit");
  }
  if (new Set(checks.map((check) => check.id)).size !== checks.length) {
    throw new Error("duplicate_check");
  }
  return {
    schema_version: "1.0",
    attempt_id: attemptId,
    snapshot_digest: snapshotDigest,
    patch_digest: patchDigest,
    files,
    edits,
    checks,
  };
}

export function shellQuote(argument: string): string {
  return `'${argument.replaceAll("'", `'"'"'`)}'`;
}

export function redactLog(value: string): string {
  let redacted = value;
  for (const pattern of SECRET_PATTERNS) redacted = redacted.replace(pattern, "[REDACTED]");
  return redacted.slice(0, MAX_LOG_BYTES);
}
