# SWE-bench Verified Expanded Preliminary Evaluation

Model: `qwen3-coder-plus`

Target tasks: 10

Actually attempted: 8

Officially evaluated: 5

Non-empty patches: 6

Patch Generation Rate: 6 / 8 = **75.00%**

Official Resolved: 4

End-to-End Resolve Rate: 4 / 8 = **50.00%**

Patch-conditional Resolve Rate: 4 / 6 = **66.67%**

NO_PATCH: 0

NO_PATCH_TOOL_BUDGET: 2

AGENT_TIMEOUT: 0

EVAL_INFRA_BLOCKED: 1

Avg Tool Calls: 35.38

Diagnosis Calls: 0

Repair Attempts: 0

| Task | Tool calls | Time (s) | Patch | Official result |
| --- | ---: | ---: | --- | --- |
| `astropy__astropy-7336` | 60 | 271.88 | No | Not submitted (`NO_PATCH_TOOL_BUDGET`) |
| `django__django-10097` | 60 | 663.48 | No | Not submitted (`NO_PATCH_TOOL_BUDGET`) |
| `django__django-10880` | 60 | 424.30 | Yes | `EVAL_INFRA_BLOCKED` |
| `django__django-10914` | 8 | 47.61 | Yes | `RESOLVED` |
| `django__django-10999` | 19 | 96.22 | Yes | `UNRESOLVED` |
| `django__django-11066` | 21 | 209.31 | Yes | `RESOLVED` |
| `django__django-11099` | 11 | 145.20 | Yes | `RESOLVED` |
| `django__django-11119` | 44 | 315.27 | Yes | `RESOLVED` |

The end-to-end denominator includes every attempted Agent task. The infrastructure-
blocked patch is not counted as resolved and is reported separately.
