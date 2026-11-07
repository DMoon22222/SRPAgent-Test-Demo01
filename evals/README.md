# B 组小规模诊断评测

本目录评估 B 对既有事实的规则诊断，不生成/修复代码，不执行目标代码，不提供检索或 O 工作流，也不调用真实 Claude API。

## 数据和评分

[diagnosis_cases.jsonl](dataset/diagnosis_cases.jsonl)包含 16 条公开、自编的回归事实样例，优先复用既有测试及规则输入，并明确标注变体来源。每条包含代码上下文、输入事实、独立预标注的分类/阶段/下一动作/证据位置及根因可确定性。它们是诊断测试夹具，不冒充新产生的 Docker 事实或独立随机样本。

预期标签在首轮评分前固定。输入中的动态身份、日期、契约关联和摘要由既有样例工具在运行时重建，输入观察及预期标签保持不变。

[run_diagnosis_eval.py](runners/run_diagnosis_eval.py)调用 B 的真实规则后端和公共 Schema，分别检查：

1. 分类、阶段和下一动作是否符合预标注。
2. 引用是否指向同一事实中的有效、非空位置，摘要是否来自该观察。
3. 引用观察是否包含预标注错误信号，诊断解释是否包含该样例要求的具体说明。
4. 无证据时是否产生特定根因假设或确定置信度。
5. 响应 Schema、身份关联、原始事实保留和零执行/零模型用量。

第 3 项是有限的确定性说明检查标准，不是独立人工语义评审，也不是通用根因正确率。专门的负例测试证明：引用位置真实存在时，编造不相关根因仍会被拒绝。完整说明与限制见[评测报告](../docs/verification/diagnosis_benchmark_20261107.md)。

## 复现

先按项目 [README](../README.md)安装 B 与兼容共同框架。规则评测不需要 API Key，以下命令在 B 仓库根目录运行：

```powershell
& '.\python_service\.venv-local-v2\Scripts\python.exe' -X utf8 -B evals/runners/run_diagnosis_eval.py --output evals/reports/diagnosis_eval_rerun.json --label rerun
```

输出文件已存在时，选择新文件名，避免覆盖已有证据。默认输出是已经保存的最终记录；不加新输出路径会明确拒绝覆盖。Windows 环境需要能正常创建临时目录及 SQLite 文件。

已有前后对照为[基线](reports/diagnosis_eval_baseline.json)、[解释改进后首次结果](reports/diagnosis_eval_after_explanations.json)和[最终文件结果](reports/diagnosis_eval.json)。分类标签、样例数和数据字节摘要在三次运行中一致；具体源码摘要和日期分别记录。

## 有界属性测试

Hypothesis 只作为可选测试工具安装到私有目录，运行时/SDK 锁文件保持原样。在 `python_service` 目录执行：

```powershell
& '.\.venv-local-v2\Scripts\python.exe' -m pip install --target .interop/hardening-tools -r requirements-hardening.txt
$env:PYTHONPATH = (Join-Path (Get-Location) '.interop\hardening-tools')
& '.\.venv-local-v2\Scripts\python.exe' -X utf8 -B -m pytest tests/property -q -p no:cacheprovider --hypothesis-show-statistics
```

三项属性分别检查非法制品、授权预算边界、跨实例重放和同身份异文拒绝，每项最多 30 个生成样例、单例 deadline 2000ms，固定生成模式且不持久化 Hypothesis 数据库。它们使用合成执行计数后端，不启动 Docker。私有工具目录不提交 Git。

真实 Docker 快速检查位于 [pre_integration_docker_smoke.py](../python_service/scripts/pre_integration_docker_smoke.py)，必须显式提供 `--docker`，并为重复运行指定新的 `--output`。报告输出对应 5 项检查，其中 CLEANUP 是观察检查，每轮实际目标执行 4 次。
