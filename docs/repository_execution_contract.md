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
