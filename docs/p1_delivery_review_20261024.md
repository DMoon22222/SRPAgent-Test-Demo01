# B 组 Local v2 修复、精简审查与 P1 交付核对

执行跨 2026-10-23 / 10-24，时区 Asia/Shanghai；机器记录使用 UTC，`2026-10-23T16:xxZ` 对应本地 10 月 24 日。先完成仓库阅读并在会话中输出实施计划，再依序修改和验证。本报告记录本次实测，不沿用 10 月 16 日的成功结论。

## 1. 版本与规范依据

| 项目 | 本次对象 |
|---|---|
| B 仓库与分支 | `DMoon22222/SRPAgent-Test-Demo01`，`b/local-v2-adapter` |
| B 基准提交 | `eb13d3b86c58497f671d1c4e313c5953c713d1a6` |
| 候选版本 | `srp-b-local 0.3.1`，固定源码提交 `c1f52e8ed321616a8e364c1d43c22568c27fe17c`；保留分支评审，不合并 |
| 核验源码集合摘要 | `57492c8b2de0821cf0ce3c5e6582ceecb7f07032bd361f8c17e40933f04383bb`，算法及 15 个文件原始字节 SHA-256 见验证 JSON |
| 共同规范远端 main | `55e9f3a945d58df60bd59ab8c57f206e3ebb67bd`，实际查询核对 |
| 本机共同框架 | `d3f46741bab412886ad39e5f7c8fac52741e506e`，含此前 B 交付登记；本轮未修改 |
| 公共契约 | schema 2.0；OpenAPI SHA-256 `07382d82cce2c748b39110b6107575acc87af2ed86e15abaddd208f84b8aceae` |
| 固定 wheel | `srp_b_local-0.3.1-py3-none-any.whl`，SHA-256 `950887b755b347cfccfec77a4d6f4c9d0428e62041934cad180d88e3dec844c2` |
| 接收确认 | 未收到 O 或其他组正式签收，不填写确认人或签名 |

发布核对：用户随后授权提交到 GitHub，已创建上述固定源码提交，并核对其 15 份源码 Git blob 与本次验证摘要一致，见 [固定版本核对记录](verification/local_v2_publication.json)。测试 JSON 中的基准提交及“未提交工作区”是实际测试时状态；不改写历史时间，也不把本次 Git 核对冒充重新执行测试。远端同步目标为 `b/local-v2-adapter` 与 PR #1。

权威依据为共同仓库 `modules/b/README.md`“最低接入交付”、`docs/01_各组实现范围与约束.md` §4、`02_接口定义与通信规范.md` §3–4、`03_数据对象规范.md` §5/7/9、`08_消息封装与数据传输格式规范.md` §2/4/6–8，以及 `11月5日真实模块接入验证里程碑.md` §2–6。已阅读对应 OpenAPI、LocalTransport、ContractRegistry、Guard、Mock、正式配置与 O 调用链。

里程碑 §3 将 10 月 25 日 P1 定义为“本组必需能力验证及来源证明，O 可独立替换一个 Mock 开展混合联调”。至少 10 个开发任务、全真实八项能力和自然全链记录属于后续整体 M1 材料与验收；不能把本次 11 个故障/成功场景当成该开发任务集，也不能把全真实 ABC 作为 B 单模块验证的先决条件。

## 2. 修改结果与实施顺序

| 优先级 | 文件 | 缺陷或缺口与处理 |
|---|---|---|
| P0 | `python_service/srp_b/diagnosis.py` | 确认并修复固定 `/stderr` 引用；分别记录真实非空日志和失败测试，测试证据优先；摘要对应实际内容；无证据时不生成假设 |
| P0 | `python_service/srp_b/module.py` | `_context` 返回带流名称的已核验日志，调用内解析后仍区分 stdout/stderr；不改失败来源、执行次数和公共接口 |
| P0 | `python_service/tests/test_local_v2.py` | 新增六项针对性测试，覆盖两种单流、双流、仅测试结果、无充分证据、受控引用日志；使用执行前配置合成后端，保持已存事实不可变 |
| P0 | `python_service/srp_b/samples.py` | 增加公开拒绝样例重建助手，仅为交付样例使用，不是业务信封新格式 |
| P0 | `python_service/scripts/verify_local_v2.py` | 导出 11 个场景；加入诊断故障注入及可解析部分事实验证；正式配置经 `build_transport` 加载；记录当前源码、关联 ID、真实/注入来源与未验证项 |
| P0 | `python_service/scripts/check_local_v2.py` | 支持业务与传输错误分类；核对样例身份、制品/日志/config 哈希、可见性、诊断指针、完成重放和源码一致性 |
| P0 | `python_service/tests/test_local_v2_samples.py`（新增） | 七项正反例测试：实际合法样例、空或越界/负索引引用、无关摘要、身份错配、公开保护拒绝配方 |
| P0 | `python_service/scripts/run_local_v2_tests.py`（新增） | 实际执行三组回归，从 JUnit XML 汇总数量；记录环境、命令、原始报告摘要和前次结果；Windows 使用短临时路径 |
| P1 | `python_service/srp_b/__init__.py`、`pyproject.toml` | 候选修复版本同步为 0.3.1，保留既有包范围与运行依赖；沙箱镜像仍为单独版本 `srp-b-python:0.3.0` |
| P1 | `.gitattributes` | 新增的适配样例测试沿用 LF，保持证据原始字节可核对 |
| P1 | `docs/contracts/v2/`、`docs/verification/local_v2_*.json` | 重新生成能力、公开样例、执行与回归记录；新增实际 wheel 内容和独立导入摘要 |
| P1 | `README.md`、`docs/local_v2_handoff.md`、本报告 | 同步功能、命令、当前候选及签收边界，保留历史能力说明 |

仅清理两处确认未使用的导入：验证脚本的 `check_public` 和测试中的 `Command`。未删除历史模块，未修改共同 Schema、Guard、O 调度或 Mock；未降低既有测试断言。原有 `.pico/`、`Test.py` 和两份未跟踪研究草稿未纳入本次修改。

## 3. 样例与证据

每个样例含场景标识、来源、完整公开基础请求、实际响应、实际请求摘要和预期结果类别。普通样例通过公共请求/响应 Schema、Guard、身份和哈希核验。

| sample_id | 证明范围 | 来源与结果类别 |
|---|---|---|
| static_failure | 真实 AST 静态失败，没有伪造执行事实 | real_static；业务 completed、报告 failed |
| static_diagnosis | 分析上述静态报告 | real_rules；业务 completed，执行调用 0 |
| execution_failure | 固定断言真实失败 | real_docker；业务 completed、测试 failed |
| execution_diagnosis | 使用该原执行事实，不重跑 | real_rules；业务 completed，执行调用 0 |
| execution_success | 实际 pytest 通过并返回非空逐项结果 | real_docker；业务 completed |
| completed_replay | 新模块实例重放完成请求，原信封/usage_id 不变 | real_adapter_replay；物理执行不新增，Usage 保留原值供去重 |
| timeout | 合成死循环受到时间限制并清理容器 | real_docker；业务 completed、执行 timeout |
| environment_failure | 请求 Python 3.99 与实际镜像不匹配 | real_docker_environment_probe；业务 completed、infrastructure_error，目标执行 0 |
| execution_not_authorized | 执行授权额度为零 | fault_injection；业务 blocked，执行调用 0 |
| protected_diagnosis_rejected | 非法保护反馈不能进入公开诊断 | fault_injection；标准 TransportErrorResponse，CONTRACT_INVALID |
| diagnosis_failure_retains_fact | 注入诊断器故障，保留此前真实执行事实 | fault_injection；业务 error，DIAGNOSIS_FAILED，partial_result_ref 可由 O 存储和 B 恢复工具解析 |

保护拒绝样例使用公开基础请求，加两个明确标量修改恢复被拒绝请求；实际错误来自恢复后的请求。`observed_request_sha256` 对应恢复后的完整输入。该输入必须未通过公共诊断 Schema 和可见性 Guard，标准错误本身通过 Schema。公开文件整体通过 `check_public`，不序列化真实保护测试、保护事实正文或私有日志。另有真实受保护执行通过和失败检查，详细原件只留在私有记录。

来源文件：[公开样例](contracts/v2/local_samples.json)、[执行证据](verification/local_v2_validation.json)、[测试证据](verification/local_v2_tests.json)、[wheel 证据](verification/local_v2_wheel.json)。前两份运行摘要与公开样例使用相同源码集合摘要，检查器重新核对 15 份源码原始字节。

## 4. 实际测试与环境

| 回归套件 | 收集 | 通过 | 失败 | 错误 | 跳过 |
|---|---:|---:|---:|---:|---:|
| B 本地适配及样例检查 | 46 | 46 | 0 | 0 | 0 |
| 共同框架 | 99 | 99 | 0 | 0 | 0 |
| 旧 B 服务 | 185 | 182 | 0 | 0 | 3 |
| 合计 | 330 | 327 | 0 | 0 | 3 |

适配与共同框架使用 `.venv-local-v2`，旧服务使用 `.venv`；各套件实际 Python 和依赖记录在 `local_v2_tests.json`。主应用 Python 3.12.4、pytest 9.1.1、pydantic 2.14.1、jsonschema 4.26.0。旧服务测试显式清空模型凭据；三个跳过项为原有 `RUN_REPOSITORY_DOCKER_SMOKE=1` 才执行的仓库烟测，未将其记为通过。

首次共同框架回归为 97 通过、2 失败：O 的哈希制品文件位于过长 pytest 路径下，Windows 返回 FileNotFoundError。仅缩短测试临时前缀，未改框架或断言，重跑 99 项全部通过。失败、后续重跑时间、数量和原因保留在 `previous_attempts`，原始 JUnit/日志留在 `.interop/p1-tests/`。

执行验证程序共 17 项检查通过，包含真实静态工具、真实 Docker、规则诊断、重放、故障注入、正式配置混合流程和容器清理核对；不将 17 项全部计为物理 Docker 执行。每项的 `evidence_kind` 和调用 `execution_calls` 分开记录。真实执行覆盖成功、断言失败、超时、OOM、信号、非 root、只读源码、授权写目录、禁网及受保护验收正反分支。

Docker Desktop 本次起初未启动，经 `docker desktop start --timeout 60` 恢复。实际 Engine 29.9.1；所用本地缓存镜像 `srp-b-python:0.3.0`，不可变 ID `sha256:f5845583361a42bef20999c1795e8d5bfb9ada8ac9e1f0552889e48e04840c32`；容器实际 Python 3.11.5、pytest 8.3.5。部署 Dockerfile 未在本次重新构建验证，不将其视为同一构建来源。墙钟时间实测，CPU 时间、峰值内存和费用未知项保留未知。

### 实际命令与复现

从 `python_service` 执行。回归脚本内部的三条 pytest 完整参数、JUnit 摘要、各套件环境记录在测试 JSON；每轮运行使用独立短临时根，由 pytest 管理临时子目录，报告与日志分别保存。

```powershell
& '.\.venv-local-v2\Scripts\python.exe' -B scripts/run_local_v2_tests.py --retry-note 'Final source-consistency run after evidence provenance labels, capability-version checks and removal of unused imports; no shared core or test assertions relaxed.'
& '.\.venv-local-v2\Scripts\python.exe' -B scripts/verify_local_v2.py --docker --output ../docs/verification/local_v2_validation.json --public-samples ../docs/contracts/v2/local_samples.json --framework-config ../../reliable_codegen_framework/config.b-local.example.json
& '.\.venv-local-v2\Scripts\python.exe' -B scripts/check_local_v2.py
& '.\.venv-local-v2\Scripts\python.exe' -m pip wheel --proxy= --no-deps --wheel-dir .interop/p1-wheel .
& '.\.venv-local-v2\Scripts\python.exe' -m pip install --no-deps --target .interop/p1-wheel/installed .interop/p1-wheel/srp_b_local-0.3.1-py3-none-any.whl
```

wheel 在源码目录之外使用 `python -I -B` 验证；显式将独立安装目录放入导入路径，确认 `srp_b` 与共享规则均来自 wheel，然后真实调用工厂、capabilities、AST 静态失败及对应规则诊断。未导入 FastAPI/A2A/MCP；50 个 wheel 条目未含 `.env`、SQLite 或 pyc。六个 `srp_b` 文件加两个共享 `app` 文件共八份运行源码，与 wheel 内原始字节摘要一致。

本次混合验证使用本机共同仓库 `b/local-v2-handoff` 提供的 `config.b-local.example.json`，配置规范 JSON 摘要 `02a8df62dec0f97b4a1301f0d41a6f18ad254018ca4b5f5cd2d01a33153bdb5b`。该文件在本机共同交付提交 `d3f4674`，尚未进入远端 main；不把它称为 O 已签收配置。经共同框架原 `build_transport` 加载公开工厂；仅覆盖 B 私有状态目录与显式镜像。保留 `adaptive_rag`、两次修复上限和 15 秒传输时限。O 运行一次修复后 accepted，未结算 Usage 列表为空；A/C 保留 Mock 标记，B 使用真实模块。运行 ID、trace 和固定工厂路径见执行摘要；这是 B 侧技术验证，不是 O 组正式签收。其他机器仅克隆远端共同 main 时，应先取得上述已核对配置，再运行命令，不能假定 main 已含此文件。

## 5. 精简审查及依赖清单

当前调用链为 `srp_b:create_module → BModule → AST / DockerRunner / diagnosis → app.analyzer.error_signal_extractor → app.schemas.RuleDecision`，同时通过 `Journal` 保留不可变事实和幂等响应。规则路径仅需 pydantic，共同契约使用 jsonschema；未发现可移除的必需运行依赖。

| 分类 | 模块/目录 | 引用与用途 | 本轮决定 |
|---|---|---|---|
| 当前 v2 必需 | `srp_b/module.py`、`diagnosis.py`、`sandbox.py`、`state.py` | 三项公开能力、真实执行与日志、持久化和版本冻结 | 保留；仅修复来源信息传递 |
| 当前 v2 必需 | `app/analyzer/error_signal_extractor.py`、`app/schemas.py`、空包初始化文件 | 诊断直接复用规则和 RuleDecision | 保留，不复制实现 |
| v2 交付/验证依赖 | `samples.py`、验证/检查脚本、测试、Dockerfile | 新鲜请求、来源检查、可复现执行和回归 | 保留；样例助手不是 O 运行必须能力 |
| v2 不直接调用但仍有依赖 | `app/api/`、`app/adapters/a2a/`、`app/adapters/mcp/`、`app/services/`、`app/tasks/`、`app/contracts/` | `app.main`、REST/A2A/MCP 互调与持久化任务；相关回归直接导入 | 保留；不能仅因 v2 不调用而删除 |
| v2 不直接调用但仍有依赖 | `app/repository/`、`app/sandbox/`、`app/config.py`、旧分析器 | 旧服务执行仓库、快照、JUnit 解析、规则/模型诊断；旧回归与服务均引用 | 保留 |
| 旧版/研究用途 | `src/`、Java 测试 | 既有 Java 控制器、执行器和分析服务 | 保留；本轮未重跑 Java 测试 |
| 旧版/研究用途 | `codepilot/` | coding agent CLI 和 MCP 接入；评测通过 pilot 调用 | 保留；本轮未重跑其研究任务或模型 |
| 旧版/研究用途 | `evaluation/`、旧接口文档 | SWE-bench 等实验工具和历史协议的可复现说明 | 保留；旧结果不能充当本轮 v2 证据 |
| 确认无引用、可安全删除 | 两处未使用导入 | 全仓当前调用分析及回归已核验 | 已删除；没有确认可安全删除的完整历史目录 |

不能删除的“重复”检查：信封/授权预算与 payload/工作区守卫分别保护不同边界；执行前二次 `_authorize` 重新核对截止；路径和写目录限制保护沙箱；SQLite `freeze/begin/save/resolve` 分别保护版本、重放、事实和引用。`create_args(workdir=None)` 用于环境探针；`resolve_fact` 有恢复用途且被测试/验证调用。未将这些机制视为冗余。

wheel 保留 `include=["srp_b*", "app*"]`。可选最小精简为仅发现 `srp_b*`、`app` 与 `app.analyzer`，但仍会携带 `app.main`、旧分析器等文件，而它们的 API/服务依赖被裁掉，造成同一 wheel 的既有导入失效。因此本轮不执行该一行裁剪。P1 之后可将共享规则及 RuleDecision 提取到独立基础包，并让 v1/v2 都导入它；该变更需另做旧导入兼容和 wheel 验证，不以复制两份规则替代拆分。

## 6. P1 验收对照

| 条目 | 分类 | 证据与边界 |
|---|---|---|
| 公开模块入口 | 已满足，有证据 | wheel 独立工厂/capabilities；正式配置 `build_transport` 加载，不启动旧服务 |
| 真实静态检查 | 已满足，有证据 | 真实 AST 失败与 StaticCheckReport，无 ExecutionResult 冒充 |
| 真实受控执行 | 已满足，有证据 | 真实 Docker 成败、环境和逐测试事实；非空通过结果 |
| 已有反馈诊断 | 已满足，有证据 | 两种模式、零新增执行；原 failure_source 不变，证据来源六类测试 |
| 公共 Schema 与 Guard | 已满足，有证据 | 46 项适配/资料测试及 11 个样例检查；非法保护输入必须拒绝 |
| 授权、预算、截止时间 | 已满足，有证据 | 原额度/快照/截止测试、零执行授权阻塞、真实 O 结算；不改变公共授权 |
| 身份、版本、哈希和来源 | 已满足，有证据 | 请求响应关联、文件/测试/config/日志摘要，版本冻结、重放与引用校验 |
| 沙箱和保护数据 | 已满足，有证据 | 真实隔离与保护正反分支，公开拒绝错误无正文泄露；不声称同进程恶意插件隔离 |
| 最低样例 | 已满足，有证据 | B README 最低场景齐全，业务 completed/blocked/error 与传输错误分别记录 |
| 当前版本验证证据 | 已满足，有证据 | 327 通过、0 失败、3 跳过；17 项执行/注入/混合检查；15 份源码一致 |
| O 独立替换 B Mock | 已满足，有技术证据 | 本机共同交付配置、原加载器及原编排，真实 B+A/C Mock accepted；配置未进入上游 main，不是组间签收 |
| 固定版本、交付登记 | 固定源码已完成，共同登记待补 | 0.3.1 已有固定源码提交，15 份源码与验证一致；共同 B/服务/交付索引仍需更新 |
| O 正式接收确认 | 未验证，依赖 O 组 | 未填写真实确认人/时间；需由 O 按版本与证据复核 |

**技术结论：当前 B 在上述固定源码、wheel 和本机环境下，三项能力、契约约束及 O 独立接入验证已达到 2026-10-25 P1 单模块能力的技术要求。源码版本已固定，但正式交付登记尚不完整：共同台账仍为 0.3.0，尚不能宣称 O 已正式验收。** 当前应记为“技术验证通过、源码版本已固定，待共同登记与接收确认”，而不是正式 P1 已完成。

未验证事项：真实 A/C 和自然全真实链、真实模型/tokenizer 材料锁定、组间正式签收、CPU/峰值内存采集、部署 Dockerfile 在新机器构建、Java/CodePilot/大规模评测及三个旧仓库 Docker 冒烟项。它们不被本次通过数量覆盖。

## 7. 后续节点

| 节点 | 待办 |
|---|---|
| 10 月 25 日之前 | 审查 0.3.1 固定提交与 wheel；更新共同 `collaboration/groups/B.json`、`integration/services.json`、`modules/b/` 的版本/验证索引，交 O 独立核验并登记实际接收意见 |
| 10 月 30 日混合收敛 | 与真实 A/C 核对连续历史、父关系、引用生命周期、实际预算和保护视图；按各组实际模型/tokenizer 补齐整体 P0 材料，保持 Mock 范围标识 |
| 11 月 3 日全链预验收 | 使用真实 A/B/C 配置，运行自然失败—诊断—检索/评估—修复—执行链，并覆盖无检索、拒绝回退及明确停止 |
| 11 月 5 日 M1 及之后 | M1 按实际来源完成核心分支与组间签收；之后再拆分共享规则包、优化 wheel、补资源测量、多语言/仓库任务与收益实验 |

用户随后授权将本轮修改提交到 GitHub；在现有分支提交并同步供审查，不合并。个人文件、私有运行目录、模型凭据和保护验收正文不纳入 Git。
