# B 组 Pre-integration Hardening 开发成果报告

日期：2026-11-07，Asia/Shanghai。分支 `b/local-v2-adapter`，HEAD `f4ed4ca`。这是当前 0.4.0 未提交工作区的 B 组轻量加固；来源由[测试汇总](verification/pre_integration_hardening_20261107.json)中的源码及数据摘要绑定。报告生成时累计约 23.2 分钟，60 分钟目标内完成主要工作。

## 目标和原有缺口

本轮只验证和改善 B 的静态/执行反馈诊断及已有边界机制。原有实现已经具备 Docker Runner、规则诊断、SDK 离线集成和定向测试；主要缺口是当前版本缺少新的小范围真实执行记录、缺少固定的小型诊断质量基准，以及 NameError/KeyError 的说明过于笼统。已有确定性边界回归继续复用，属性测试补充输入组合，不重写守卫。

## 实际完成的改进

| 项目 | 文件/实现 | 实际成果 |
|---|---|---|
| 真实 Docker 快速回归 | [专用驱动](../python_service/scripts/pre_integration_docker_smoke.py)，调用公开 B 工厂并委托原生 Runner，跟踪容器用于清理检查 | SUCCESS、TEST_FAILED、TIMEOUT、OUTPUT_LIMIT、CLEANUP 共 5 项通过；最终轮目标执行 4 次，无遗留容器 |
| 固定事实诊断基准 | [16 条 JSONL](../evals/dataset/diagnosis_cases.jsonl)、[评分驱动](../evals/runners/run_diagnosis_eval.py) | 分类/阶段/Schema 各 16/16，引用有效性 22/22；独立记录地址有效与结论说明检查 |
| 两类异常解释 | [规则提取器](../python_service/app/analyzer/error_signal_extractor.py) | NameError/KeyError 的具体说明检查由 14/16 改为 16/16；不改变分类、证据、公共 Schema 或下一动作 |
| 有界属性测试 | [property 目录](../python_service/tests/property/) | 三项属性各 30 个生成样例，最终轮共 90 个，全部通过；使用合成计数后端 |
| 负例与回归 | [新增诊断测试](../python_service/tests/test_pre_integration_diagnosis.py)和直接相关现有测试 | 新增 8 个 pytest 测试项、复用 95 项现有测试；最终 103/103 通过，包含既有 44 项离线 SDK 测试 |
| 工程检查 | Ruff 0.16.4；只检查本次 6 份 Python 文件 | 最终零诊断；Bandit/pip-audit 未安装，明确跳过 |

输出限制场景通过 pytest 内置 capfd.disabled() 将目标输出送入原有输出限制器，没有修改 Runner 命令或安全政策。镜像始终是本地既有 image ID `sha256:f5845583361a42bef20999c1795e8d5bfb9ada8ac9e1f0552889e48e04840c32`，实际 Python 为 3.11.5、pytest 为 8.3.5，不拉取新镜像。

## 测试结果

| 套件/检查 | 通过 | 失败 | 跳过 | 性质 |
|---|---:|---:|---:|---|
| 最终 Docker 快速检查 | 5 | 0 | 0 | 真实 Docker；4 次目标执行 |
| 最终诊断基准 | 16 | 0 | 0 | 真实规则；合成固定输入事实 |
| 定向 pytest | 103 | 0 | 0 | 合成执行计数、真实规则/Schema、内存 HTTP SDK |
| 其中新增测试 | 8 | 0 | 0 | 上一行的子集，不能重复相加 |
| 其中属性测试 | 3 | 0 | 0 | 上一行的子集；90 个生成输入，不能另计为 90 个测试项 |
| Ruff 文件检查 | 6 | 0 | 0 | 单位是文件，不是测试用例 |
| Bandit / pip-audit | — | — | 2 项工具 | 未安装，不宣称审计通过 |

最终 Docker 耗时 19.157 秒，最终诊断评分 2.734 秒，定向 pytest 的 JUnit 时长 39.245 秒。各项并行或包含重复验证，不能将其时长之和当成总墙钟时间。

首轮 Docker 5/5、首轮 pytest 103/103 均保留。Ruff 整理和驱动异常处理、来源记录完善后重跑相同范围以绑定最终文件。两轮 Docker 合计 8 次目标执行；两轮 pytest 共 206 次测试项调用，但不同测试项仍为 103 个；属性输入两轮合计 180 个，最终轮 90 个。基准三次共 48 次诊断调用，独立样例始终只有 16 条。

基线的两项说明检查失败没有删除，见[基线结果](../evals/reports/diagnosis_eval_baseline.json)。初次受限进程的 Docker 访问、临时目录 SQLite 访问及工具安装失败按环境启动问题记录，样例执行数为 0；后续使用现有进程权限完成，不放宽 Docker 政策。首次 Ruff 的 11 条格式/异常捕获诊断已修正，未重构其他历史模块。

## 与 A/C/O 的职责边界

本次没有生成、修复或交付 PatchCandidate，没有实现检索决策、知识检索、查询改写、证据重排或 EvidenceBundle 评估，也没有实现 O 工作流、全局预算分配、跨组调用顺序或修复循环。测试中使用既有样例助手构造 B 输入夹具，属于测试数据准备。

B 仍只交付静态事实、执行事实、错误分类、根因假设、证据、建议和实际/未知用量。共同规范仓库、公共 Schema、公开业务操作、Docker 安全策略及运行时/SDK 锁文件均保持原样。真实 Claude API 调用为 0。

## 尚未完成及结果限制

- Bandit 和 pip-audit 未安装，本轮不安装额外审计工具，不给出依赖无漏洞或完整安全审计结论。
- 16 条样例是已用于改进解释的开发回归集；说明检查采用有限词语/事实规则，不代表通用语义正确率或独立留出集效果。
- CPU 时间、峰值内存和独立结构化 traceback 帧未在本轮扩展，原有未知值保持未知。
- 真实 Claude、干净依赖环境安装、完整 Docker/P2 矩阵、O 独立接收及全真实 A/C 联调仍需后续证据。
- 本轮真实 Docker 是五类定向检查，不能据此把 0.3.1 历史矩阵、O 签收或 M1 改为通过。

## 交付、复现和 Git 状态

复现命令见 [evals README](../evals/README.md)；[诊断评测报告](verification/diagnosis_benchmark_20261107.md)解释标签和分母；[组会单页](group_meeting_update_20261107.md)可直接用于汇报。指定输出路径已存在时，驱动拒绝覆盖，需要为复验选择新文件名。

当前工作仍在原分支，未提交、未推送、未合并。开始前的 README 修改和原有未跟踪文档/文件已保留；本轮仅追加 README 入口，没有将这些内容一并提交。原始 SQLite/请求响应、JUnit、工具安装和日志留在忽略的私有 `.interop/` 或测试临时目录，公开摘要单独保存。

下一阶段优先扩大独立标注的诊断样例，细化结构化错误证据，改进资源采集，再按选定版本配合 O 接收及 A/C 接入。
