# SWE-bench Verified Preliminary Evaluation

Dataset: SWE-bench/SWE-bench_Verified

Subset: fixed 3-instance public subset

Model: CodePilot-SRP/openai/qwen3-coder-plus

| Metric | Value |
| --- | ---: |
| Evaluated Tasks | 2 |
| Resolved Tasks | 1 |
| Resolve Rate | 50.00% |
| Avg Tool Calls | 53.00 |
| Avg Repair Attempts | 1.50 |
| Avg Diagnosis Calls | 2.00 |
| Diagnosis Trigger Rate | 50.00% |
| Repair-after-Diagnosis Success Rate | 0.00% |
| Avg Duration Seconds | 313.97 |
| Patch Generation Rate | 66.67% |
| Tool Budget Exhaustion Rate | 33.33% |

## Per-instance Results

| Instance | Official Result | Tool Calls | Repairs | Diagnoses | Duration (s) |
| --- | --- | ---: | ---: | ---: | ---: |
| astropy__astropy-7166 | OFFICIAL_UNRESOLVED | 52 | 3 | 4 | 428.797 |
| astropy__astropy-14309 | RESOLVED | 54 | 0 | 0 | 199.141 |
| astropy__astropy-14995 | PENDING_OFFICIAL_EVAL | 60 | 0 | 0 | 765.36 |

> This is a preliminary fixed-subset result, not the full 500-instance SWE-bench Verified score.

> Retrieval execution is not implemented in this MVP; only retrieval signals are counted.
