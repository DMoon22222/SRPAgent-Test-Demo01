# Repository Execution Contract

## Phase 4.1 scope

Phase 4.1 freezes the request, response, status, and extension-point contract for
future repository-level test execution. It does not copy, inspect, mount, or
execute the supplied workspace. A valid request therefore receives HTTP 501 by
design until an isolated repository runner exists.

The existing endpoint remains the single-file/snippet API:

```text
POST /api/execute-and-analyze
```

The new, separate repository endpoint is:

```text
POST /api/execute-repository
```

The two modes are intentionally not combined into one request schema.

## Request

`RepositoryExecutionRequest` contains:

| Field | Type | Default | Contract |
| --- | --- | --- | --- |
| `workspacePath` | string | required | Must contain non-whitespace text; existence is not checked in Phase 4.1. |
| `runner` | `pytest` | `pytest` | Runner profile, not a shell command. |
| `testTargets` | string array | `[]` | Future runner-specific test selectors. |
| `timeoutSeconds` | integer | `60` | Inclusive range `1..600`. |
| `benchmark` | string | `""` | Optional source label only. |

Example:

```json
{
  "workspacePath": "F:\\temp\\project",
  "runner": "pytest",
  "testTargets": ["tests/test_math.py"],
  "timeoutSeconds": 60,
  "benchmark": ""
}
```

There is deliberately no `command` field. Clients cannot send shell fragments,
pytest command strings, PowerShell, Bash, Maven commands, or command chains.
Future implementations translate a validated runner profile into a fixed
server-owned command. Unknown request fields are rejected, so an attempted
`command` field receives HTTP 422 instead of being silently accepted.

Phase 4.1 accepts only `pytest`. Phase 4.3 will implement that runner first;
Maven is reserved for Phase 4.5 and is currently rejected with HTTP 422.

## Response

The future successful response type is `RepositoryExecuteAndAnalyzeResult`:

```text
execution: RepositoryExecution
analysis: ErrorAnalysisResult | null
```

`analysis` is only a compatibility extension point in Phase 4.1. Repository
diagnosis is deferred to Phase 4.4; the existing `ErrorAnalyzer` is unchanged.

`RepositoryExecution` contains:

```text
success
status
failedStage
runner
timeout
exitCode
executionTimeMs
summary: RepositoryTestSummary
failures: RepositoryTestFailure[]
stdout
stderr
observation: RepositoryObservation | null
```

It intentionally has no single-program `expectedOutput` or `actualOutput`.

`RepositoryTestSummary` contains `total`, `passed`, `failed`, and `skipped`.
`RepositoryTestFailure` contains only `testId`, `message`, `location`, and a
compact `excerpt`; it is not a full traceback store.

`RepositoryObservation` contains:

```text
observationId
runner
status
shortSummary
importantSignals
failingTests
stdoutTruncated
stderrTruncated
nextActionHint
```

This shape is designed to expose a compact failure set to an Agent instead of
placing an entire test log into its context.

## Status semantics

The frozen status vocabulary for repository execution is:

| Status | Meaning |
| --- | --- |
| `SUCCESS` | Selected repository tests completed successfully. |
| `TEST_FAILED` | Tests ran and at least one test failed. |
| `TIME_LIMIT_EXCEEDED` | The bounded repository run exceeded its timeout. |
| `ENVIRONMENT_ERROR` | Required runner or host/container environment was unavailable. |
| `SANDBOX_ERROR` | Isolated execution infrastructure failed. |
| `COMPILE_ERROR` | Reserved for a runner with a distinct compilation phase. |

The corresponding `failedStage` vocabulary is `NONE`, `PRE_CHECK`, `COMPILE`,
`TEST`, `RUNTIME`, and `SANDBOX`. Phase 4.1 freezes these meanings but does not
implement each execution path.

## Current HTTP 501 behavior

After request validation, `/api/execute-repository` returns HTTP 501 with a
message that the Repository Runner is not implemented until Phase 4.3. Invalid
requests still return HTTP 422 through FastAPI/Pydantic validation.

HTTP 501 is the expected Phase 4.1 result, not a service defect. The API path,
request validation, response model, and runner interface now exist, while the
Repository Snapshot, Docker runner, and test-result parser do not. The endpoint
does not call the runner interface yet and never fabricates `success=true`.

## Runner extension point

`python_service/app/repository/base.py` defines the abstract
`RepositoryRunner.run(RepositoryExecutionRequest) -> RepositoryExecution`
interface. Phase 4.1 includes no `DockerRepositoryRunner` implementation.

## Security boundary and roadmap

`workspacePath` is a local trusted-integration contract field, not permission to
execute an arbitrary path. Before repository execution is enabled, Phase 4.2
must add allowed-root validation, canonical resolution, path-escape and symlink
protection, an isolated snapshot, and a guarantee that the original workspace is
not mounted writable.

Phase 4.3 will add the first fixed-profile pytest Docker runner and compact test
parsing. Phase 4.4 will add repository diagnosis and the CodePilot Tool adapter.
Phase 4.5 will add Maven support. SWE-bench integration remains outside these
contract and runner phases.

## Phase 4.2 Repository Workspace Security

Phase 4.2 adds a server-side `RepositoryWorkspaceManager` without changing the
HTTP contract or invoking a Repository Runner. The policy flow is:

```text
workspacePath
  → configured Allowed Root
  → canonical resolution and containment check
  → symlink/junction/reparse scan
  → controlled filesystem copy
  → disposable snapshot outside the source
  → ownership-checked cleanup
```

### Allowed Root and canonical paths

`REPOSITORY_ALLOWED_ROOT` is server configuration and defaults to an empty
string. An empty value disables snapshot creation with the explicit error
`repository allowed root is not configured`; it does not affect snippet
execution. Clients cannot override this policy through
`RepositoryExecutionRequest`.

Both the allowed root and requested workspace use `expanduser`, absolute-path
normalization, and canonical `resolve`. Relative workspace paths are interpreted
only beneath the allowed root. Containment uses `Path.relative_to`, not string
prefix comparison, so `..` escapes, sibling-prefix tricks, outside absolute
paths, and Windows cross-drive paths are rejected safely. The resolved workspace
must exist and be a directory.

### Link and reparse-point policy

The first version is strict: a workspace root or copied tree entry identified as
a symlink, Windows junction, or reparse point rejects the snapshot. Checks use
`Path.is_symlink()`, `Path.is_junction()` when available, and the Windows reparse
file attribute. Scanning and copying use `os.scandir`; link checks occur before
`is_dir(follow_symlinks=False)` or `is_file(follow_symlinks=False)`. Excluded
directories are checked at their boundary and are never traversed or copied.

### Snapshot and exclusions

Snapshots are controlled copies of the current filesystem state, including
uncommitted edits. Git worktrees are not used. The default manager-owned root is:

```text
%TEMP%\srp_repository_snapshots\repo_<uuid>
```

For example:

```text
F:\allowed\project
  → validate and scan
  → %TEMP%\srp_repository_snapshots\repo_<uuid>
  → future Phase 4.3 runner receives only the snapshot path
```

The server-owned exclusion set is `.git`, `.venv`, `venv`, `node_modules`,
`target`, `build`, `dist`, `__pycache__`, `.pytest_cache`, `.mypy_cache`,
`.ruff_cache`, `.pico`, `.idea`, and `.vscode`. Source and test directories plus
project manifests such as `pyproject.toml`, `requirements.txt`, and `pom.xml`
remain available. Clients cannot supply exclusion patterns.

Copying is performed entry by entry after a pre-scan and repeats the unsafe-link
check during the copy. Files are independent copies: modifying or deleting a
snapshot file cannot modify or delete the source workspace.

### Cleanup and limitations

`snapshot_workspace()` is a context manager and removes the snapshot on normal
exit and when the enclosed operation raises. Cleanup accepts only a
`RepositorySnapshot` path recorded as owned by the same manager, requires it to
be a direct `repo_` child of the manager's snapshot root, refuses linked paths,
and explicitly refuses the source path. It never deletes a request path.

This local trusted-integration boundary uses validate → scan → controlled copy
to reduce path-escape risk. It does not claim complete protection against a
malicious process concurrently mutating the source filesystem; OS-level TOCTOU
hardening remains future work.

`POST /api/execute-repository` still returns HTTP 501 in Phase 4.2. The endpoint
does not create a snapshot, execute repository pytest, invoke Docker, parse test
output, or fabricate a result. Phase 4.3 should compose the existing
`RepositoryWorkspaceManager.snapshot_workspace()` context manager with a new
isolated pytest runner that receives only `snapshot.snapshot_path`.
