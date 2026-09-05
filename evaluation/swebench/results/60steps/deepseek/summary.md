# SWE-bench Verified Preliminary Evaluation

Dataset: SWE-bench/SWE-bench_Verified

Subset: fixed 3-instance public subset

Model: CodePilot-SRP/deepseek/deepseek-v4-pro

| Metric | Value |
| --- | ---: |
| Evaluated Tasks | 1 |
| Resolved Tasks | 1 |
| Resolve Rate | 100.00% |
| Avg Tool Calls | 60.00 |
| Avg Repair Attempts | 0.00 |
| Avg Diagnosis Calls | 0.00 |
| Diagnosis Trigger Rate | 0.00% |
| Repair-after-Diagnosis Success Rate | N/A |
| Avg Duration Seconds | 119.12 |
| Patch Generation Rate | 33.33% |
| Tool Budget Exhaustion Rate | 100.00% |

## Per-instance Results

| Instance | Official Result | Tool Calls | Repairs | Diagnoses | Duration (s) |
| --- | --- | ---: | ---: | ---: | ---: |
| astropy__astropy-14309 | RESOLVED | 60 | 0 | 0 | 119.125 |
| astropy__astropy-14995 | PENDING_OFFICIAL_EVAL | 60 | 0 | 0 | 145.391 |
| astropy__astropy-7166 | PENDING_OFFICIAL_EVAL | 60 | 0 | 0 | 103.812 |

> This is a preliminary fixed-subset result, not the full 500-instance SWE-bench Verified score.

> Retrieval execution is not implemented in this MVP; only retrieval signals are counted.
