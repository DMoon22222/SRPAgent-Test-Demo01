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
