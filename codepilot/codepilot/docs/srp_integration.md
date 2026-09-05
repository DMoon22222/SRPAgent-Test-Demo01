# SRP Integration

## Architecture

```text
CodePilot
→ SrpClient
→ SRP FastAPI
→ Docker Sandbox
→ Rule-first Diagnosis
```

`SrpClient` is an independent communication boundary. It serializes requests,
performs HTTP calls, validates the minimum response shape, and returns SRP's
execution and analysis data without reclassifying or rewriting it.

## Phase 1 Status

Phase 1 provides only the HTTP client. It does not provide the
`execute_and_diagnose` Tool, Agent Runtime integration, Repair Loop, Retrieval,
Repository Execution, or SWE-bench support. CodePilot agents cannot invoke SRP
until a later phase registers a Tool adapter.

## Configuration

```dotenv
PICO_SRP_ENABLED=false
PICO_SRP_BASE_URL=http://127.0.0.1:8080
PICO_SRP_TIMEOUT_SECONDS=60
```

`SrpClient()` reads these variables when explicit constructor values are not
provided. `PICO_SRP_ENABLED` defaults to false and is exposed for later
integration wiring; it does not silently block an explicit client call.

`ping()` sends `GET /api/ping` and returns `True` for a successful HTTP response.
Connection, timeout, and non-2xx responses raise their corresponding explicit
client exceptions.

`execute_and_analyze()` sends `POST /api/execute-and-analyze` with this contract:

```json
{
  "problem": "...",
  "language": "python",
  "code": "...",
  "stdin": "",
  "expectedOutput": "...",
  "benchmark": ""
}
```

It returns the SRP JSON object after checking that `execution` is an object and
that `analysis`, when non-null, is an object. Diagnostic fields such as
`errorType`, `needRetrieval`, and `repairSuggestion` remain owned by SRP.

## Failure Boundary

An unavailable SRP service is not a user-code compile or runtime error.
`SrpConnectionError`, `SrpTimeoutError`, and `SrpHttpError` represent transport
or service failures. `SrpResponseError` represents invalid JSON or a response
contract violation. Only a valid SRP response describes the submitted program's
execution and diagnosis.

## Phase 2 Agent Tool

Phase 2 adds this agent-visible path when `PICO_SRP_ENABLED=true`:

```text
CodePilot Agent
→ execute_and_diagnose
→ SrpClient
→ SRP FastAPI
→ Docker Sandbox
→ Rule-first Diagnosis
→ Agent-facing Observation
→ AgentLoop history
→ next model decision
```

`SrpToolProvider` is assembled beside the Builtin and optional MCP providers.
When SRP is disabled its `discover()` method returns no tools, so the default
CodePilot tool list and behavior remain unchanged.

The Tool accepts a workspace-relative code path plus optional problem, language,
stdin, expected output, and benchmark values. The existing workspace path guard
resolves the path and rejects traversal, outside absolute paths, and symlink
escape before the file is read. Python aliases `python3` and `py` are normalized
to `python`; Java is passed as `java`.

The Tool is marked `risky=false` because it does not mutate the CodePilot
workspace and submitted code executes in the SRP isolated sandbox. Its metadata
explicitly records `execution_isolated=true`. This classification does not make
the submitted code trusted; it identifies where execution occurs.

The Agent-facing Observation keeps execution status, stage, timeout, exit code,
duration, SRP diagnosis, evidence, repair suggestion, retrieval signal, and SRP's
short observation fields. Raw stdout, stderr, error log, rule decision, and
classification internals are omitted by default to keep history bounded.

`run_shell` remains available for ordinary host-side repository commands such as
Git and pytest. `execute_and_diagnose` is specifically for isolated execution of
a workspace code file and structured SRP diagnosis.

SRP connection, timeout, HTTP, and response-contract failures produce a Tool
error with a distinct `tool_error_code`; they are never represented as a user
program compile or runtime error. Phase 2 returns `needRetrieval` and
`retrievalQuery` as signals only—it does not perform Retrieval or an automatic
Repair Loop.

## Phase 3 Controlled Repair Loop

Phase 3 keeps the existing AgentLoop and makes its model-directed repair cycle
observable:

```text
Agent
  ↓
model-selected Patch
  ↓
execute_and_diagnose
  ↓
structured Observation
  ↓
model-selected Patch
  ↓
Retest
  ↓
SUCCESS / repair budget record / existing finalization
```

`pico/repair_trajectory.py` records this sequence. It never chooses a patch and
contains no mapping from an SRP error type to repair code. A Repair Attempt is
counted at an `execute_and_diagnose` boundary only when the diagnosed path has
actually changed through a successful `patch_file` or `write_file` call since
the previous boundary. Reads, searches, multiple edits before the boundary, and
an unrelated documentation edit do not add attempts by themselves.

Each valid SRP response records the execution status, failed stage, error type,
error subtype, suspected location, affected path, retrieval signal, and the
previous/current diagnosis. The diagnosis fingerprint is the stable string:

```text
executionStatus|failedStage|errorType|errorSubtype|suspectedLocation
```

Free-form `rootCause` text is deliberately excluded. Two consecutive identical
failed fingerprints set `repeatedDiagnosis=true`; the Observation and the next
prompt then ask the model to reconsider its approach without prescribing a fix.
Transitions record only whether the fingerprint changed—they do not label a new
diagnosis as better or worse.

`PICO_SRP_MAX_REPAIR_ROUNDS` defaults to `3`. It is separate from AgentLoop
`max_steps`: the former counts changed-code → diagnosis boundaries, while the
latter bounds all Tool calls. This low-intrusion first version records
`repair_round_limit_exceeded` and `repair_stop_reason=repair_round_limit`, adds a
stop/summarize instruction to the next model prompt, and relies on the existing
AgentLoop tool-budget finalization instead of killing the Runtime or synthesizing
an answer.

A successful SRP result sets `repairSucceeded=true` and
`finalExecutionStatus=SUCCESS`; the model still writes the final answer. An SRP
transport/service failure is stored under `infrastructure_failures`, does not
increment diagnosis calls or create a diagnosis transition, and leaves a pending
changed path available for a later retry. `needRetrieval` and `retrievalQuery`
are recorded only; Phase 3 adds neither a Retrieval Tool nor automatic web
search.

The complete state is saved in the existing session and checkpoint structures,
and `report.json` exposes it as `repair_summary`. `trace.jsonl` continues to use
the existing Tool events, enriched with repair iteration, fingerprint, repeat,
limit, success, and retrieval metadata. No new persistence system is introduced.

Phase 3 remains single-file/code-snippet execution. It does not implement
repository test execution, worktrees, SWE-bench, or any Phase 4 capability.

### Phase 3 real smoke status (2026-09-05)

The existing SRP FastAPI application started locally on `127.0.0.1:8080`.
`GET /api/ping` succeeded both directly and through `SrpClient.ping()`. The local
Docker Desktop daemon was unavailable, so the requested SUCCESS and
DIVIDE_BY_ZERO execution cases are recorded as
`REAL_SMOKE_BLOCKED_BY_DOCKER`; the end-to-end model repair example is recorded
as `REAL_REPAIR_SMOKE_BLOCKED`. No SRP server or sandbox code was changed to hide
this environment limitation.

## Phase 4.1 Status

The SRP server now defines a separate Repository Execution Contract at
`POST /api/execute-repository`. Phase 4.1 performs request validation and returns
HTTP 501 because snapshotting and the Repository Runner are intentionally not yet
implemented. CodePilot Runtime and its Tool registry remain unchanged; repository
execution will be connected to CodePilot in Phase 4.4.

## Phase 4.2 Status

Repository allowed-root validation, canonical path containment, strict
symlink/junction protection, isolated filesystem snapshots, and ownership-checked
cleanup are ready on the SRP server. `/api/execute-repository` still returns 501;
CodePilot does not yet expose or execute a repository Tool.

## Phase 4.3 Status

The SRP server now executes repository pytest through an allowed-root validated,
disposable Snapshot and a fixed-profile Docker runner. Docker receives only the
Snapshot path; the Original Workspace is never mounted. JUnit parsing produces
the existing compact `RepositoryExecution` contract, while repository
`analysis` remains null. CodePilot Runtime and its Tool registry are unchanged;
there is still no CodePilot repository Tool until Phase 4.4.

## Phase 4.4 Repository Tool

The existing `SrpToolProvider` now exposes two parallel tools when
`PICO_SRP_ENABLED=true`:

- `execute_and_diagnose` executes one Python or Java source file.
- `execute_repository_and_diagnose` executes pytest for the complete current
  CodePilot workspace through `POST /api/execute-repository`.

The repository Tool schema exposes only `test_targets`, `timeout_seconds`, and
`benchmark`; it never accepts `workspacePath`, an absolute host path, a runner,
or a command. The Provider obtains the canonical repository root from the
existing `ToolContext.root`, fixes the runner to pytest, and the SRP server still
mounts only its disposable Snapshot in Docker.

The Agent receives summary counts, up to five failing tests and representative
failures, bounded signals, execution status, and the rule-first diagnosis. Raw
stdout and stderr are deliberately omitted from Agent history. A pytest failure
is a successful Tool invocation with a code diagnosis; HTTP/service errors and
`ENVIRONMENT_ERROR`/`SANDBOX_ERROR` are infrastructure failures and do not count
as diagnosis transitions.

`RepairTrajectory` treats repository execution as an additional diagnosis
boundary. All effective files changed since the previous repository boundary
form one repair attempt, regardless of the number of edits or reads. It retains
the Phase 3 fingerprint, repeated-diagnosis threshold of two, shared default
maximum of three rounds, retrieval-signal-only behavior, and model-owned final
answer. The AgentLoop itself is unchanged.
