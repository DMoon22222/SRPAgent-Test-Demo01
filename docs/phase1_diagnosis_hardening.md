# B 组第一阶段专项加固交付

日期：2026-11-07。B 0.4.0，分支 `b/local-v2-adapter`，起点/结束 HEAD 均为 `b4a1684fc44a088ca7dab1cf0ff572bad225ca7c`。本轮修改保持**未提交、未推送、未合并**。这是 B 内部工程加固，不代表 O 签收、P2/M1 完成或 A/C/O 真实全链路通过。

## 完成内容

| 方向 | 原有问题 | 本轮结果 |
|---|---|---|
| 候选评测 | 只有 16 条开发回归，缺少独立审核准备和分母区分 | 冻结 40 条来源明确的新候选，保留初标、基线、首次失败和最终结果；增加分类/证据/拒答指标与混淆矩阵；人工审核 n=0 单列 null |
| 结构化错误 | 后续 Agent 仍需重复解析文本 | 有界 Python 多帧、SyntaxError、pytest 短帧及两类异常链解析；原始事实不变，派生对象有指针/摘要/行级来源，已有 traceback 字段可直接消费 |
| 置信度 | 单个旧分数混合分类与根因，弱证据也可能确定归因 | 分类和根因分开评估；关键词、截断、冲突、测试来源及无证据时降分/UNKNOWN；旧字段形状不变，通过 extensions 保存规则依据 |
| 资源观测 | CPU/峰值内存未采集，墙钟口径包含准备与清理 | 只读 Engine 旁路采集累计 CPU、观测内存峰值、时间与限制事件；不可用为 null；容器先清理，再回收监控，避免可选监控延迟清理 |

技术审查与 S0–S6 顺序见[实施计划](phase1_implementation_plan.md)，起始工作区见[保护快照](verification/phase1_workspace_inventory.json)。开始时上一轮工作已经在 b4a1684 发布，不是任务背景中假设的未提交状态；原有用户未跟踪内容得到保留。

## 验证结果和实际分母

| 范围 | 最终结果 | 说明 |
|---|---|---|
| 原有 103 项 + 新增 52 项 | 155/155 通过 | 独立定向运行通过；最终完整运行也覆盖同样 155 项并全部通过 |
| 新增单元测试 | 52/52 通过 | Traceback 21、置信度 15、资源 12、评分脚本 4 |
| 完整 pytest | 384 通过、7 失败、3 跳过，共 394 | 已执行两轮；最终 119.48s，不能描述为全绿 |
| 原有 16 条开发集 | 16/16 通过 | 分类、阶段、动作、证据/说明规则、Schema；原数据与断言未改 |
| 新候选初标一致性 | 分类/动作/阶段各 40/40 | 40/40 成功评分，调用/Schema 错误为 0；不是人工独立泛化成绩 |
| Hypothesis | 3 属性、90 个生成样例通过 | 每属性 30，0 failing/invalid；包含于 pytest 项，不额外计作 90 项测试 |
| 真实 Docker | 8/8 检查通过 | 每轮 7 次目标执行 + 清理观察；三轮共 21 次目标执行，另有 runtime 探针 |
| Ruff | 12 文件检查，0 新增、4 条历史告警 | 使用 python_service 作为工作目录；全范围并非零告警 |
| Bandit / pip-audit | 未执行 | 当前未安装，也没有 CLI；未安装新工具或改依赖锁 |
| 真实 Claude API | 0 | SDK 集成仅使用内存 HTTP 传输 |

完整套件的 7 个失败均来自固定 **0.3.1** 的历史 P2 manifest 与当前 **0.4.0** 的 `IMPLEMENTATION_VERSION_MISMATCH` 保护。已从 HEAD 只读导出原始 B 源码至私有目录，复跑同 7 个节点，失败节点与原因一致；包装层返回 failed 的一个节点也检查了其临时 summary 的实际 error_code。没有为当前版本重写历史 manifest、测试断言或旧证据。3 个 skipped 是未启用的旧 repository Docker 接口验收；本轮真实 Docker 仅使用专用自编驱动。详情及节点见[最终边界记录](verification/phase1_boundary_final.json)。

Ruff 的旧告警为 Claude 构造参数 ValueError/TypeError 建议、SDK 异常边界两处 broad-except、close 的空处理。与 HEAD 输入运行 Ruff 的规则/消息逐项一致，本轮没有通过改旧语义或批量忽略来消除它们。首次从仓库根执行时另有 6 个导入分类提示；Ruff 的 first-party 判断依赖工作目录，最终固定从 Python 项目目录复现。首轮与最终结果均保留。

## Mock、合成事实与真实执行

pytest 里的执行计数后端、Docker 命令/stats 响应及错误注入是 Mock/合成夹具；44 项 Claude 测试使用真实 SDK + 内存 MockTransport，未连接供应商。完整套件还运行旧 HTTP/A2A/MCP 的本地测试与自编夹具，不代表真实 A/C 算法联调。两个诊断评分驱动运行真实规则，目标执行和模型用量均为 0。

真实 Docker 三轮使用既有 `srp-b-python:0.3.0`，镜像 ID `sha256:f5845583361a42bef20999c1795e8d5bfb9ada8ac9e1f0552889e48e04840c32`；实际 Python 3.11.5、pytest 8.3.5。7 个自编场景为 SUCCESS、TEST_FAILED、TIMEOUT、OUTPUT_LIMIT、HIGH_CPU、HIGH_MEMORY、OOM，另检查 CLEANUP。高内存为 24MiB 分配保持，OOM 为 512MiB 分配受到原 256MiB 限制。不是运行不可信外部代码。

最终报告保存 CPU 累计观测、内存采样最大值、采样数/间隔、OOMKilled/退出/超时/输出限制及线程和容器清理。短窗口可能采不到 CPU/内存；首轮 SUCCESS 曾明确 unavailable，原值保留。即使最终采到值，也不称为精确完整生命周期峰值；快速 OOM 的采样峰值可能远低于限制。墙钟是宿主 start/attach 区间，包含 CLI 延迟；原宿主超时机制并非 cgroup 的精确墙钟终止保证，不把 nominal timeout 与实测时间混为一谈。采集口径见[资源设计](resource_monitoring_design.md)。

## 候选集的统计限制

40 条中 4 条历史真实 Docker、1 条历史真实 AST、1 条历史环境探测，另 34 条合成对抗；所有标签都是 Codex 初标、pending_review，**独立人工审核数 0，独立人工指标 null**。历史事实来自开发夹具且已被开发者见过，新合成场景也不是盲测。原 16 条不合并进入候选泛化分数。

冻结初标的分类一致率由 34/40 到 40/40，Macro-F1 由 0.8966 到 1.0000；有限 Unsupported 规则由 27/40 到 0/40，拒答/信息收集由 6/40 到 17/40。这说明本轮已覆盖的模式和证据规则更保守，不能说明真实根因准确率 100%、零幻觉或概率已校准。完整定义、矩阵和前后对照见[评测报告](verification/phase1_diagnosis_benchmark.md)。

## 变更文件和兼容性

业务接入仅修改已有 [diagnosis.py](../python_service/srp_b/diagnosis.py)、[sandbox.py](../python_service/srp_b/sandbox.py)、[claude.py](../python_service/srp_b/claude.py)。新增内部 [structured_errors.py](../python_service/srp_b/structured_errors.py)、[confidence.py](../python_service/srp_b/confidence.py)、[resource_monitor.py](../python_service/srp_b/resource_monitor.py)。没有新增公开业务操作或改变工厂调用方式。

新增 4 份 phase1 单元测试、[评分驱动](../evals/runners/run_diagnosis_eval_phase1.py)、[Docker 驱动](../python_service/scripts/phase1_docker_smoke.py)、[候选数据](../evals/dataset/diagnosis_candidates_phase1.jsonl)、[标注规范](../evals/dataset/annotation_guide.md)、[来源说明](../evals/dataset/data_sources_phase1.md)、3 份设计、计划及独立验证材料。精确清单和逐文件摘要见[机器汇总](verification/phase1_test_summary.json)。

复用公共已有 extensions、StackFrame 和 number/null confidence。旧 RuleDecision 及旧服务调用保持不变；Local v2 的旧 confidence 现在明确为根因评分，消费方若用固定阈值解释分类确定性，需要改读分类扩展。异常类型和动作的保守变化有针对性测试，旧 16 条分类/动作回归最终完整通过。

共同规范工作区保持干净，公共契约 SHA256 仍为 `07382d82cce2c748b39110b6107575acc87af2ed86e15abaddd208f84b8aceae`。23 份历史基线/报告/源码和 3 个用户文件的起始摘要逐一一致，`.pico/` 保留。Docker validate_policy/create_args/_cleanup、bounded_command、JUnit 读取/解析六个函数 AST 与 HEAD 一致。原 1MiB 输出硬限、32KiB 保留、network none、read-only、CPU/内存/PID/权限和清理策略没有降低；运行时锁、公共 Schema、A/C/O 代码均未改。

## 复现

使用现有本地 B 与兼容框架环境，规则模式不需要 API Key。无新依赖安装；当前完整测试环境由已有 `.venv`、`.venv-local-v2` 包和框架路径组合，**不是一次干净独立安装验证**。在其他机器按原项目安装说明建立相同依赖，再运行测试；不要机械复制本机环境路径或声称已验证独立安装。

仓库根复现两个评测的命令见[评测报告](verification/phase1_diagnosis_benchmark.md)。以下在 `python_service` 执行，所有输出用新文件名：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) '.interop\hardening-tools')
& '.\.venv-local-v2\Scripts\python.exe' -X utf8 -B -m pytest tests/test_local_v2.py tests/test_local_v2_samples.py tests/test_local_v2_claude.py tests/test_error_signal_extractor.py tests/test_pre_integration_diagnosis.py tests/property tests/test_phase1_traceback.py tests/test_phase1_confidence.py tests/test_phase1_resource_monitor.py tests/test_phase1_eval_metrics.py -q -p no:cacheprovider --hypothesis-show-statistics --junitxml=.interop/phase1/review-targeted.xml
& '.\.venv-local-v2\Scripts\python.exe' -X utf8 -B scripts/phase1_docker_smoke.py --docker --output ../docs/verification/phase1_docker_review_rerun.json
ruff check --no-cache srp_b/structured_errors.py srp_b/confidence.py srp_b/resource_monitor.py srp_b/diagnosis.py srp_b/sandbox.py srp_b/claude.py tests/test_phase1_traceback.py tests/test_phase1_confidence.py tests/test_phase1_resource_monitor.py tests/test_phase1_eval_metrics.py scripts/phase1_docker_smoke.py ../evals/runners/run_diagnosis_eval_phase1.py
```

本机完整套件复现：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) '.interop\hardening-tools') + ';' + (Join-Path (Get-Location) '.venv-local-v2\Lib\site-packages') + ';F:\srpTest\reliable_codegen_framework'
$env:DASHSCOPE_API_KEY = ''
$env:LLM_API_KEY = ''
$env:ANTHROPIC_API_KEY = ''
$env:RUN_REPOSITORY_DOCKER_SMOKE = '0'
& '.\.venv\Scripts\python.exe' -X utf8 -B -m pytest tests -q -p no:cacheprovider --hypothesis-show-statistics --junitxml=.interop/phase1/review-full.xml
```

完整套件保留上述 7 个历史失败是预期重现结果，不应靠降低断言“修绿”。Windows 环境需要可用的临时 SQLite/目录和 Docker 本地管道访问权限；这不要求改变容器安全参数。私有 JUnit、原始请求/响应和环境不提交 Git，公开机器汇总保存其摘要、计数和来源。

## 保留的中间结果与后续工作

旧 16 条首轮 15/16、候选首轮动作 39/40、Ruff 首次根目录导入判断、最小环境缺旧依赖、基线隔离导出/收集路径错误均保留记录。最终修正包括 TimeoutExpired 识别、区分 pytest 短帧与标准缺终端栈、长任务样本保留上限与累计最大值分离，以及容器先清理后回收监控。没有覆写旧数据、旧报告或隐藏失败。

仍待独立人工审核与外部新真实样例、根因语义评价和概率校准、ExceptionGroup 树/更多自定义格式、其他平台/并发资源压力验证、干净环境安装及可选审计工具。Java 原生 Local v2 执行链路当前不支持，本轮没有虚构 Java 实测。旧 P2 清单的 0.4.0 迁移需要独立受控更新和真实接收证据；本轮未擅自修改。真实 Claude、O 接收、A/C 真正接入和正式里程碑验收继续待后续授权与对应材料。
