# CodePilot × SRP SWE-bench Verified MVP

This directory contains a deliberately small evaluation adapter. It prepares a
frozen public SWE-bench Verified subset, invokes the existing `pilot` CLI in a
fresh session for each task, exports repository diffs in the official prediction
format, and merges verdicts produced by the official SWE-bench Harness.

The checked-in selection is a **preliminary SWE-bench Verified fixed 3-instance
subset**, not a score for the full 500-instance benchmark. Retrieval execution
is not implemented in this MVP; only existing retrieval-request signals are
counted.

## Frozen subset and integrity

The selector reads `SWE-bench/SWE-bench_Verified`, filters by the lowest
published difficulty bucket (`<15 min fix`), sorts by `instance_id`, and takes
the first three rows. The frozen IDs are:

1. `astropy__astropy-14309`
2. `astropy__astropy-14995`
3. `astropy__astropy-7166`

`selected_instances.json` contains only public task metadata, the issue text,
the deterministic selection reason, and any environment skip reason. Gold
patches, test patches, hidden test names, and Harness logs are never passed to
the Agent. The selection must not be changed based on Agent outcomes.

To regenerate the selection before an evaluation starts:

```powershell
F:\srpTest\swebench_eval\.venv\Scripts\python.exe -m evaluation.swebench.select_instances `
  --output evaluation\swebench\selected_instances.json `
  --limit 3
```

## 1. Evaluation dependencies

Keep the Harness outside CodePilot's runtime environment:

```powershell
uv venv F:\srpTest\swebench_eval\.venv
uv pip install --python F:\srpTest\swebench_eval\.venv\Scripts\python.exe swebench
git clone https://github.com/SWE-bench/swe-bench-tasks.git `
  F:\srpTest\swebench_eval\swe-bench-tasks
```

Inspect the installed command instead of assuming a version-specific syntax:

```powershell
F:\srpTest\swebench_eval\.venv\Scripts\swebench.exe eval --help
```

Docker Desktop must use Linux containers on an x86-64 host. Allow roughly 120
GB for official images and caches. The evaluation environment, task repository,
Docker images, and cloned benchmark workspaces are intentionally not committed.

## 2. Model and SRP configuration

Configure the chosen provider through the existing CodePilot environment. Never
put credentials in commands, result files, or logs. Freeze one provider, model,
temperature, step limit, and repair limit for the whole subset.

Start SRP with the benchmark workspace root explicitly allow-listed:

```powershell
cd F:\srpTest\execution-diagnosis\python_service
$env:REPOSITORY_ALLOWED_ROOT='F:\srpTest\swebench_workspaces'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18080
```

The MVP run uses SRP as an internal execution/diagnosis signal. Missing
repository dependencies in SRP are not benchmark verdicts; only the official
Harness decides `Resolved` or `Unresolved`.

## 3. CLI checks

CodePilot already exposes `pilot = "pico.cli:main"`, a positional one-shot
prompt, and `--cwd`; this adapter does not duplicate or replace the Agent loop.

```powershell
cd F:\srpTest\execution-diagnosis\codepilot\codepilot
uv run pilot --help
uv run pilot --cwd F:\path\to\workspace "Fix the issue described in the prompt."
```

Running `uv run pilot --cwd F:\path\to\workspace` without a prompt starts the
unchanged interactive shell. `/exit` exits normally.

## 4. Prepare one instance

Each instance gets a disposable, independent checkout. Existing instance
directories are removed only beneath the explicit workspace root and recreated
from the public source repository:

```powershell
cd F:\srpTest\execution-diagnosis
F:\srpTest\execution-diagnosis\codepilot\codepilot\.venv\Scripts\python.exe `
  -m evaluation.swebench.prepare_instance `
  --selected evaluation\swebench\selected_instances.json `
  --instance-id astropy__astropy-14309 `
  --workspaces-root F:\srpTest\swebench_workspaces
```

Preparation verifies detached `HEAD == base_commit` and a clean worktree.

## 5. Run the existing Agent

The following is the reproducible one-instance shape. Supply credentials only
through the process environment. The example values are the frozen MVP settings:

```powershell
cd F:\srpTest\execution-diagnosis
$env:PICO_SRP_ENABLED='true'
$env:PICO_SRP_BASE_URL='http://127.0.0.1:18080'
$env:PICO_SRP_MAX_REPAIR_ROUNDS='3'

F:\srpTest\execution-diagnosis\codepilot\codepilot\.venv\Scripts\python.exe `
  -m evaluation.swebench.run_instance `
  --selected evaluation\swebench\selected_instances.json `
  --instance-id astropy__astropy-14309 `
  --workspaces-root F:\srpTest\swebench_workspaces `
  --codepilot-root F:\srpTest\execution-diagnosis\codepilot\codepilot `
  --results-dir evaluation\swebench\results `
  --provider openai --model qwen3-coder-plus `
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 `
  --temperature 0 --max-steps 60 --max-new-tokens 2048 `
  --max-repair-rounds 3 --wall-timeout 1800
```

Run the entire frozen subset sequentially with durable per-instance output:

```powershell
F:\srpTest\execution-diagnosis\codepilot\codepilot\.venv\Scripts\python.exe `
  -m evaluation.swebench.run_subset `
  --selected evaluation\swebench\selected_instances.json `
  --workspaces-root F:\srpTest\swebench_workspaces `
  --codepilot-root F:\srpTest\execution-diagnosis\codepilot\codepilot `
  --results-dir evaluation\swebench\results `
  --provider openai --model qwen3-coder-plus `
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 `
  --temperature 0 --max-steps 60 --max-new-tokens 2048 `
  --max-repair-rounds 3 --wall-timeout 1800
```

Completed rows are skipped by default; `--force` explicitly reruns them. Every
instance starts from a fresh checkout and a new CLI process/session. A timeout or
empty patch remains in the results rather than being silently discarded.

Repository-level evaluation defaults to 60 tool calls and a 1,800-second wall
timeout. The runtime includes used/remaining metadata on every turn and
non-mandatory convergence notices at 20, 10, and 5 remaining calls. The hard
tool stop remains active, and final-answer text is never converted into a patch.

## 6. Export predictions

`run_instance` automatically exports the diff from the frozen base commit. The
exporter includes legitimate untracked source files and excludes `.pico`, cache,
session, SRP, and benchmark runtime artifacts. It never commits inside a task.

For a manual export:

```powershell
F:\srpTest\execution-diagnosis\codepilot\codepilot\.venv\Scripts\python.exe `
  -m evaluation.swebench.export_prediction `
  --workspace F:\srpTest\swebench_workspaces\astropy__astropy-14309 `
  --base-commit cdb66059a2feb44ee49021874605ba90801f9986 `
  --instance-id astropy__astropy-14309 `
  --model-name CodePilot-SRP/openai/qwen3-coder-plus `
  --predictions evaluation\swebench\results\predictions.jsonl
```

## 7. Gold sanity and official Harness evaluation

Use only the official Harness for verdicts. First sanity-check the environment
with the official gold path, at one worker and only the frozen instance IDs:

```powershell
F:\srpTest\swebench_eval\.venv\Scripts\swebench.exe eval verified --gold `
  -i astropy__astropy-14309 --run-id phase45-gold-14309 -j 1 -t 1800 `
  --report-dir F:\srpTest\swebench_eval
```

Then evaluate generated predictions:

```powershell
F:\srpTest\swebench_eval\.venv\Scripts\swebench.exe eval verified `
  -p F:\srpTest\execution-diagnosis\evaluation\swebench\results\predictions.jsonl `
  -i astropy__astropy-14309 -i astropy__astropy-14995 -i astropy__astropy-7166 `
  --run-id phase45-codepilot-srp -j 1 -t 1800 `
  --report-dir F:\srpTest\swebench_eval
```

On Linux, official images can be built from the official task repository with
`swebench images build <task-repo> -i <instance-id>`. The 5.0.2 image-builder
imports the Unix-only `resource` module, so on native Windows the same official
task Dockerfile can be built directly and tagged with the exact `image` value in
that task's `task.yaml`. Image-build/pull failures are recorded as
`EVAL_INFRA_BLOCKED`; they are never counted as Agent failures or unresolved
tasks.

## 8. Aggregate metrics

Pass the JSON report written by the official Harness:

```powershell
F:\srpTest\execution-diagnosis\codepilot\codepilot\.venv\Scripts\python.exe `
  -m evaluation.swebench.aggregate_results `
  --results-dir evaluation\swebench\results `
  --selected evaluation\swebench\selected_instances.json `
  --official-results F:\srpTest\swebench_eval\CodePilot-SRP.phase45-codepilot-srp.json
```

Rates use only tasks with a real official Boolean verdict. A zero denominator is
written as JSON `null`, never as a fabricated 0%.

## Outputs

- `selected_instances.json`: frozen public selection metadata.
- `results/predictions.jsonl`: official prediction rows and model patches.
- `results/agent_runs.jsonl`: one durable Agent/trace/repair metadata row per task.
- `results/summary.json`: machine-readable fixed-subset metrics.
- `results/summary.md`: report-ready metrics and per-instance results.
- `results/report_snapshot.md`: concise phase-report data snapshot.
- `results/cli_demo.txt`: scrubbed CLI smoke command, tool sequence, and status.
- `results/agent_logs/`: scrubbed detailed run logs; ignored by Git.
- `results/official/`: optional copied raw Harness artifacts; ignored by Git.

Run adapter tests explicitly; real model and Docker evaluation are not part of
ordinary pytest:

```powershell
F:\srpTest\execution-diagnosis\codepilot\codepilot\.venv\Scripts\python.exe `
  -m pytest evaluation\swebench\tests -q
F:\srpTest\execution-diagnosis\codepilot\codepilot\.venv\Scripts\ruff.exe `
  check evaluation
```
