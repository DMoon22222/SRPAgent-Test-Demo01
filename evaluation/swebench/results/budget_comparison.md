# SWE-bench 12-step vs 60-step budget comparison

Evaluation unit: one fixed SWE-bench Verified instance. Agent-side metrics use all
three fixed instances for each model. Official resolve rates use only non-empty
patches submitted to the official SWE-bench Harness.

| Model | Budget | Tasks | Avg. tool calls | Patches | Patch rate | Budget exhausted | Diagnosis calls | Repair attempts | Official resolved |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen `qwen3-coder-plus` | 12 | 3 | 12.00 | 0 | 0.00% | 3/3 | 0 | 0 | N/A |
| Qwen `qwen3-coder-plus` | 60 | 3 | 55.33 | 2 | 66.67% | 1/3 | 4 | 3 | 1/2 (50.00%) |
| DeepSeek `deepseek-v4-pro` | 12 | 3 | 12.00 | 0 | 0.00% | 3/3 | 0 | 0 | N/A |
| DeepSeek `deepseek-v4-pro` | 60 | 3 | 60.00 | 1 | 33.33% | 3/3 | 0 | 0 | 1/1 (100.00%) |

The larger budget removed the universal `NO_PATCH` failure mode: three of six
model/task runs produced non-empty patches, and two of the three submitted patches
resolved their instances. The remaining empty-patch runs are classified as
`NO_PATCH_TOOL_BUDGET`.

Official Harness notes:

- Qwen resolved `astropy__astropy-14309` and did not resolve `astropy__astropy-7166`.
- DeepSeek resolved `astropy__astropy-14309`.
- `astropy__astropy-14995` produced no patch for either model and was not submitted.
- On Windows, the external Harness installation was adjusted to write generated
  `eval.sh` and `patch.diff` files with LF line endings. Gold patches resolved for
  both evaluated images after this platform-only compatibility adjustment; grading
  logic was unchanged.
