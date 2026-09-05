# SWE-bench Verified Preliminary Evaluation

Dataset: SWE-bench/SWE-bench_Verified

Subset: fixed 3-instance public subset

Model: CodePilot-SRP/openai/qwen3-coder-plus

| Metric | Value |
| --- | ---: |
| Evaluated Tasks | 0 |
| Resolved Tasks | 0 |
| Resolve Rate | N/A |
| Avg Tool Calls | N/A |
| Avg Repair Attempts | N/A |
| Avg Diagnosis Calls | N/A |
| Diagnosis Trigger Rate | N/A |
| Repair-after-Diagnosis Success Rate | N/A |
| Avg Duration Seconds | N/A |
| Patch Generation Rate | 0.00% |
| Tool Budget Exhaustion Rate | 100.00% |

## Per-instance Results

| Instance | Official Result | Tool Calls | Repairs | Diagnoses | Duration (s) |
| --- | --- | ---: | ---: | ---: | ---: |
| astropy__astropy-14309 | PENDING_OFFICIAL_EVAL | 12 | 0 | 0 | 45.469 |
| astropy__astropy-14995 | PENDING_OFFICIAL_EVAL | 12 | 0 | 0 | 56.984 |
| astropy__astropy-7166 | PENDING_OFFICIAL_EVAL | 12 | 0 | 0 | 52.203 |

> This is a preliminary fixed-subset result, not the full 500-instance SWE-bench Verified score.

> Retrieval execution is not implemented in this MVP; only retrieval signals are counted.
