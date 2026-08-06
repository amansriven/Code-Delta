# Phase 3: repository intelligence

- **Status:** Implemented deterministic foundation
- **Contract version:** `1.0`
- **Depends on:** [Phase 2 official-source ingestion](phase-2-ingestion.md)

## Delivered boundary

Phase 3 consumes durable `change_fanout_jobs` and turns each job into an
immutable repository snapshot, deterministic dependency inventory, and
repository-specific impact assessment. Only an `affected` assessment creates a
migration. This phase does not generate a plan or patch, execute repository
code, or publish to GitHub.

The implementation provides:

- strict GitHub clone-identity validation and installation-token resolution
  through an opaque credential handle;
- detached, ephemeral Git workspaces resolved to an exact 40-character commit
  SHA, with credentials absent from the checkout configuration and result;
- bounded deterministic SHA-256 workspace fingerprints that exclude known
  generated/vendor directories and never follow symbolic links;
- language detection plus static parsing of `pyproject.toml`,
  `requirements*.txt`, `package.json`, and `package-lock.json`;
- normalized PyPI and npm dependency evidence with manifest or lockfile
  provenance, including exact PyPI pin comparison against compatible affected
  ranges;
- a Python AST analyzer for import aliases, constructor aliases, called
  symbols, exact endpoint constants, keyword arguments, and literal dictionary
  fields, plus positive-only JavaScript/TypeScript lexical evidence;
- explicit `affected`, `unaffected`, `uncertain`, and `unsupported` outcomes
  with file counts, parse failures, excluded files, unsupported languages,
  limitations, confidence, and stable call-site identifiers;
- atomic snapshot, dependency, call-site, assessment, migration, audit, and job
  lifecycle persistence; and
- workspace-scoped, cursor-paginated snapshot and impact APIs.

## Analysis flow

```text
durable repository fan-out job
  -> atomically claim queued job
  -> resolve GitHub installation credential from opaque handle
  -> validate repository identity and fetch requested branch
  -> resolve exact commit and hash bounded workspace
  -> inventory languages, manifests, lockfiles, and dependencies
  -> parse Python and scan bounded JavaScript/TypeScript without executing them
  -> match normalized targets to dependencies and static call sites
  -> persist immutable snapshot and impact evidence atomically
  -> create one idempotent queued migration only when affected
  -> delete ephemeral checkout
```

The inventory is change-independent. The analyzer consumes the immutable
inventory and one normalized change, so the same snapshot can be assessed
against multiple provider events without changing its identity.

## Outcome semantics

| Conclusion | Meaning |
| --- | --- |
| `affected` | At least one deterministic manifest, lockfile, symbol, endpoint, or field match exists. |
| `unaffected` | No target matched and every observed code language/file was covered by the Python AST analyzer. |
| `uncertain` | No target matched, but a parse/inventory warning, excluded file or link, or unsupported code language prevents a safe negative conclusion. |
| `unsupported` | No supported Python, JavaScript, or TypeScript source was available. |
| `failed` | Reserved by the evidence contract; infrastructure failures are currently recorded on the durable fan-out job with a safe error code. |

`unaffected` is never produced from text search, model inference, partial
coverage, or absence of a supported analyzer. An affected finding can retain
incomplete coverage when deterministic evidence exists in the supported
portion of a mixed-language repository.

## HTTP resources

```text
GET /repositories/{repository_id}/snapshots
GET /changes/{change_id}/impacts
GET /impact-assessments/{assessment_id}
```

Every query is scoped by the authenticated workspace. Snapshot and impact
feeds use the same opaque timestamp/id cursor convention as the control plane.

## Safety boundary

Repository-controlled scripts, package managers, imports, build hooks, and
model calls are never invoked. Static files are limited to a 2 MB analysis
size; the complete workspace is limited to 50,000 files and 200 MB. Known
vendor/build directories are skipped, and symbolic links are recorded in the
workspace fingerprint but not traversed or parsed.

Git installation tokens exist only inside the checkout provider. They are not
included in persisted repository metadata, workspace contracts, error codes,
inventory warnings, task arguments, or analyzer inputs.

## Current limitations

- Python is the only semantic language implementation. JavaScript and
  TypeScript have deterministic positive-only lexical matching; a negative
  scan remains uncertain. Go, Java, Kotlin, Ruby, Rust, C#, and PHP are detected
  and produce explicit partial or unsupported coverage.
- Dynamic dispatch, reflection, computed endpoints/field names, generated
  clients without ordinary Python syntax, and runtime dependency injection are
  not resolved.
- Dependency inventory covers the initial PyPI/npm manifest formats above; it
  does not yet infer provider associations independent of normalized targets.
- Repository fetches currently analyze the configured default branch at the
  commit resolved when the job runs. Webhook-pinned commit selection is a later
  orchestration refinement.

## Phase 4 handoff

Phase 4 may consume only persisted normalized changes, immutable snapshot and
inventory digests, deterministic call sites, impact confidence, and explicit
limitations. It must keep `uncertain` and `unsupported` work out of automatic
patch generation unless a developer explicitly requests a bounded review.

Generation must produce schema-validated plans and exact patch artifacts; any
repository commands must run through the sandbox contract. The trusted worker
must not install dependencies, invoke repository scripts, or claim checks
passed.
