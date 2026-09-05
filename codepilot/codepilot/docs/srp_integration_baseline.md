# CodePilot × SRP Execution & Diagnosis 融合基线

> 基线日期：2026-09-05
> 当前阶段：Phase 0（仅建立融合前基线，尚未开始 SRP HTTP Client 或 Tool Adapter 实现）

## 1. 当前项目信息

- 原始任务指定路径：`F:\srpTest\codepilot_v2-master`
- Phase 0 实际源码根目录：`F:\srpTest\codepilot_v2-master\codepilot_v2-master\codepilot`
- 当前融合仓库中的源码目录：`codepilot/codepilot`
- 规划文档位置：`F:\srpTest\CODEX_CODEPILOT_SRP_FUSION_PLAN.md`
- Python：`3.12.4`
- uv：`0.11.1 (a6042f67f 2026-03-24)`
- Phase 0 Git 状态：当时的交付目录没有 `.git`，因此未获得 branch、commit、HEAD 和 remote；用户明确允许在不依赖 Git 元数据的情况下继续。
- 项目包：`pico 0.1.0`
- Python 要求：`>=3.10`

Phase 0 时，源码根目录比规划路径多两层嵌套，项目主 README 位于源码根目录的上一级。后续融合仓库已将 CodePilot 完整导入 `codepilot/` 子目录；运行 Python 开发命令时，应以包含 `pyproject.toml`、`pico/` 和 `tests/` 的 `codepilot/codepilot` 为工作目录。

## 2. 当前测试基线

### 2.1 环境同步

```text
uv sync
```

结果：成功。创建 `.venv`，解析 11 个包并安装 8 个包。uv 报告无法跨文件系统 hardlink，已自动回退为复制；这是性能警告，不影响依赖安装结果。

### 2.2 完整 pytest

```text
uv run pytest tests -q
```

结果：

- 收集/执行测试：160
- passed：148
- failed：12
- skipped：0
- warnings：6
- 首次总耗时：165.24 秒
- 文档新增后复跑：仍为 148 passed、12 failed、6 warnings，没有新增失败
- 总体状态：失败

失败分类如下：

| 类别 | 数量 | 说明 |
| --- | ---: | --- |
| 缺少依赖 / Windows 时区数据 | 4 | `ZoneInfo("Asia/Shanghai")` 无法加载；当前开发依赖没有声明 `tzdata`。 |
| Benchmark / shell 跨平台问题 | 4 | verifier 使用 `python3` 或 POSIX 单引号命令；Windows `shell=True` 下不兼容。另外过滤后的 shell 环境在测试场景中缺少 `%ComSpec%` / `%SystemRoot%`。 |
| 源码与测试契约漂移 | 3 | DeepSeek 源码默认值为 `deepseek-v4-flash`，README、`.env.example` 和测试期望为 `deepseek-v4-pro`（2 项）；欢迎界面测试仍期望旧 ASCII 图形（1 项）。 |
| Windows 权限限制 | 1 | 当前账户没有创建符号链接所需权限，安全边界测试在准备 fixture 时失败。 |

这些失败是融合前仓库的既有基线，Phase 0 未修改业务代码或测试来消除它们。

### 2.3 核心模块定向测试

```text
uv run pytest tests/test_cli.py tests/test_agent_loop.py tests/test_tool_executor.py tests/test_tools.py -q
```

结果：`10 passed in 3.17s`。CLI、AgentLoop、ToolExecutor 和内置 Tool 的核心定向用例通过。仓库没有规划文字中提到的独立 `tests/test_tool_registry.py`；Tool Registry 的行为由其他测试间接覆盖。

CLI 入口使用 `uv run pilot --help` 验证成功，无需连接模型服务。

### 2.4 Ruff

```text
uv run ruff check pico tests scripts
```

结果：失败，共报告 95 个 lint 问题，其中 42 个可由普通 `--fix` 自动修复，另有 12 个需要 unsafe fixes 才能自动修改。Phase 0 没有执行自动修复。

### 2.5 测试体系

- `tests/` 包含 24 个 `test_*.py` 文件。
- 单元/契约测试覆盖 AgentLoop、TaskState、ToolExecutor、内置工具、allowlist、Context Manager、Memory、Checkpoint、Session/Run Store、安全约束、Provider、MCP、CLI 和公共 API。
- `pico/evaluation/` 包含 `evaluator.py`、`metrics.py` 和 `phase4.py`，用于固定 benchmark、消融指标以及 Skill/MCP/Tool Governance 集成评测。
- `benchmarks/coding_tasks.json` 定义 12 个确定性 harness 回归任务。

## 3. 当前 Agent Runtime 结构

```text
User Task
→ Pico.ask()
→ AgentLoop.run()
→ 创建 TaskState 与 Run 目录
→ ContextManager 构建 Prompt
→ Model Client 返回文本决策
→ Pico.parse() 解析 <tool> 或 <final>
→ ToolExecutor 校验、审批并执行 Tool
→ Tool Result 写入 Session History
→ 更新 TaskState / Memory / Trace
→ 创建 Checkpoint
→ 下一轮 Model Decision
→ Final Answer
→ 最终 Checkpoint / Report
```

各组件职责：

- **AgentLoop**：支持连续多轮 Tool Call。`max_steps` 默认值为 6；模型尝试上限为 `max(max_steps * 3, max_steps + 4)`。工具预算耗尽后会额外请求一次只能返回最终答案的 finalization。
- **Tool Registry**：从 Builtin/MCP 等 Provider 调用 `discover()`，校验统一 Tool Spec、检测重名，并应用本次任务的 Tool allowlist。
- **ToolExecutor**：执行 Tool 存在性、参数、重复调用、风险审批检查；对 risky Tool 执行前后采集 workspace 快照，并统一返回内容和 metadata。
- **TaskState**：记录 `run_id`、`task_id`、状态、tool steps、model attempts、last tool、stop reason、final answer、checkpoint 和 resume 状态，并持续写入 `task_state.json`。
- **History**：用户消息、模型消息和 Tool Result 保存在 session history；Tool Result 会作为下一轮 Prompt 的历史证据重新提供给模型。
- **Trace**：按 JSONL 追加记录 `run_started`、`prompt_built`、`model_requested`、`model_parsed`、`tool_executed`、`checkpoint_created`、`run_finished` 等事件。
- **Report**：运行结束后汇总 TaskState、Prompt metadata、工具步数、尝试次数、停止原因、checkpoint、持久记忆提升和脱敏信息。
- **Checkpoint**：在 Tool 执行后、上下文缩减、freshness/workspace mismatch、模型错误和运行结束等节点创建；包含关键文件 freshness 和 Runtime identity，支持恢复时判断是否过期。
- **Memory**：包含 working、episodic、durable/topic 等层次。文件读取可形成摘要，写入/patch 会使旧摘要失效；部分稳定事实可提升为 durable memory。
- **Context Manager**：按固定顺序拼装 prefix、checkpoint、memory、relevant memory、history 和 current request，并按字符预算压缩旧历史与次要内容。
- **Prompt Prefix**：提供工作区事实、Tool Schema、风险标记和文本工具协议。模型必须输出一个 `<tool>...</tool>` 或 `<final>...</final>`；当前不是 Provider-native function calling。
- **Provider**：支持 Ollama、OpenAI-compatible Responses、Anthropic-compatible Messages 和 DeepSeek Anthropic-compatible。选择优先级为 CLI 参数、`PICO_*` 环境变量、旧环境变量、代码默认值；API key 只从环境读取。

运行工件默认保存在工作区：

```text
.pico/sessions/<session_id>.json
.pico/runs/<run_id>/task_state.json
.pico/runs/<run_id>/trace.jsonl
.pico/runs/<run_id>/report.json
```

## 4. 当前 Tool 列表

未显式传入 `--mcp-config` 时，内置 Tool 共 7 个：

| Tool | 主要用途 | risky | 逻辑只读 | 可能修改 workspace |
| --- | --- | --- | --- | --- |
| `list_files` | 列出工作区目录内容 | false | 是 | 否 |
| `read_file` | 按行范围读取 UTF-8 文件 | false | 是 | 否 |
| `search` | 使用 `rg` 或 Python fallback 搜索工作区 | false | 是 | 否 |
| `run_shell` | 在仓库根目录执行普通宿主机命令 | true | 否 | 是，命令可产生任意工作区副作用 |
| `write_file` | 创建或覆盖文本文件 | true | 否 | 是 |
| `patch_file` | 精确替换唯一文本块 | true | 否 | 是 |
| `delegate` | 启动步数受限、`approval=never` 的只读子 Agent 调查任务 | false | 是 | 否 |

当显式提供可信的 `--mcp-config` 时，Registry 还会发现 `mcp.<server_id>.<tool_name>` 工具。MCP Server 声明在 `read_only_tools` 中的工具按只读处理，其余 MCP Tool 按 risky 处理。当前默认启动没有额外 MCP Tool。

ToolExecutor 会为正常、失败和拒绝结果记录统一 metadata，主要字段包括：

```text
tool_status
tool_error_code
security_event_type
risk_level
read_only
affected_paths
workspace_changed
workspace_fingerprint
diff_summary
```

## 5. 当前 `run_shell` 行为

`run_shell` 是 CodePilot 的普通仓库命令工具，不是 SRP 的 Docker 隔离执行环境。

- 在 CodePilot 宿主机进程中执行。
- 使用 Python `subprocess.run(..., shell=True)`。
- `cwd` 固定为 Agent workspace 根目录。
- 捕获 stdout、stderr 和 exit code，并把它们编码为文本 Tool Result。
- timeout 默认 20 秒，参数允许范围为 1～120 秒。
- 环境变量经过 allowlist 过滤。默认候选为 `HOME`、`LANG`、`LC_ALL`、`LC_CTYPE`、`LOGNAME`、`PATH`、`PWD`、`SHELL`、`TERM`、`TMPDIR`、`TMP`、`TEMP`、`USER`，并强制设置 `PWD`；当前列表没有 Windows 的 `ComSpec` 和 `SystemRoot`。
- Tool 被标记为 risky。默认 `approval=ask` 会交互确认，`auto` 自动允许，`never` 拒绝执行；只读 delegate 使用 `approval=never`。
- 执行前后采集 workspace 文件哈希快照，生成 `affected_paths`、`workspace_changed` 和 `diff_summary`。
- 非零退出码会映射为 `error`；若命令失败但已修改工作区，则映射为 `partial_success`。
- 没有容器、文件系统隔离、资源配额、网络隔离或恶意代码防护，因此不能用来替代 SRP Docker Sandbox。

## 6. 后续融合目标

```text
CodePilot
= Agent Runtime / Tool Routing / Repo Search / Patch /
  Context / Memory / Checkpoint / Repair Loop

SRP
= Docker Sandbox / Compile & Run / Execution Feedback /
  Rule-first Diagnosis / Root Cause / Evidence /
  needRetrieval / repairSuggestion
```

未来通过两层适配连接：

```text
CodePilot execute_and_diagnose Tool
→ 独立 SRP HTTP Client
→ SRP POST /api/execute-and-analyze
→ Docker Sandbox + Rule-first Diagnosis
→ 结构化 Agent Observation
→ CodePilot 下一轮决策
```

融合时必须保持以下边界：

- 不复制 SRP Rule-first 分类逻辑到 CodePilot。
- 不用 `run_shell` 替代 SRP Docker Sandbox。
- 不让 SRP ErrorAnalyzer 负责 Runtime Tool Routing、RAG 或自动修复循环。
- CodePilot 只消费 SRP 返回的 Execution、Diagnosis 和 AgentObservation，并决定搜索、检索、patch、重测或停止。

## 7. Phase 1 预计新增文件

Phase 1 只规划、不在 Phase 0 创建：

```text
pico/integrations/__init__.py
pico/integrations/srp_client.py
tests/test_srp_client.py
```

建议继续采用以上路径，因为当前项目已经按 `pico/providers/`、`pico/features/`、`pico/mcp/` 和 `pico/evaluation/` 划分边界，独立的 `pico/integrations/` 能让 SRP HTTP 序列化逻辑避免进入 `runtime.py`。

Phase 1 应先完成纯 HTTP Client 和 mock 测试，不注册 `execute_and_diagnose`，不修改 AgentLoop。Phase 2 再通过 Tool Provider/Registry 接入 Tool Adapter。

## 8. Phase 0 边界确认

Phase 0 未实现以下内容：

- `execute_and_diagnose`
- SRP HTTP Client
- RAG / Retrieval
- SWE-bench
- 自动修复闭环
- AgentLoop 重构
- SRP Rule-first 逻辑复制
- SRP 项目修改

## Phase 0.5：Monorepo 基线

> 冻结日期：2026-09-05
> 阶段边界：仅确认 Monorepo、测试和目录基线，未开始 Phase 1。

### Git 与目录基线

- Git Root：`F:\srpTest\execution-diagnosis`
- 当前分支：`master`
- Phase 0.5 开始时的 commit：`1bde8d19acb847a3a837d78915de99ea5261c90a`
- 主远端：`origin = https://github.com/DMoon22222/SRPAgent-Test-Demo01.git`
- CodePilot 来源远端：`codepilot-source = https://github.com/DMoon22222/codepilot_v2.git`，仅用于保留上游来源，不构成独立仓库。
- CodePilot subtree 位置：`F:\srpTest\execution-diagnosis\codepilot`
- CodePilot subtree 导入提交：`f31ad88`，导入的上游提交为 `d1199d6`；两者在导入时的 Git tree 完全一致。
- CodePilot Python 根目录：`F:\srpTest\execution-diagnosis\codepilot\codepilot`
- SRP Python 根目录：`F:\srpTest\execution-diagnosis\python_service`
- `codepilot/`、`codepilot/codepilot/` 和 `python_service/` 均不存在内部 `.git`。

整个融合项目共用一套 Git 历史。正式开发、提交和回滚均以 `F:\srpTest\execution-diagnosis` 为唯一 Git 工作区，不得在子目录重新初始化仓库。

### 测试与质量基线

- CodePilot 完整 pytest：`148 passed, 12 failed, 0 skipped, 6 warnings`。允许保留这 12 个融合前已知失败，但后续不得新增失败。
- 已知失败类别：Windows 缺少 `tzdata`、Windows shell 兼容性、symlink 权限、默认模型配置与测试契约漂移、欢迎界面测试契约漂移。
- CodePilot 核心 Runtime 定向测试：`10 passed in 3.17s`，后续必须保持全部通过。
- CodePilot 全仓 Ruff：95 个历史问题。暂不清理；后续新增或修改的 Python 文件必须通过 Ruff。
- SRP Python 服务现有测试：`8 passed, 1 warning in 0.15s`。警告来自 Windows 下 pytest 缓存目录不可写，不影响用例结果。
- Phase 0.5 没有修改 Python 源码。由于当前子树源码与 Phase 0 已验证的上游提交一致，且核心测试已复验，本阶段不重复执行耗时的 CodePilot 全量 pytest 和全仓 Ruff。
- 后续每个 Phase 新增的测试必须 100% 通过。

### SRP 结构确认

- FastAPI 入口：`python_service/app/main.py`
- Docker Sandbox：`python_service/app/sandbox/docker_sandbox.py`
- Local Sandbox：`python_service/app/sandbox/local_sandbox.py`
- ErrorAnalyzer：`python_service/app/analyzer/error_analyzer.py`
- Rule-first 信号提取：`python_service/app/analyzer/error_signal_extractor.py`
- `AgentObservation`、`RuleDecision` 及错误字段：`python_service/app/schemas.py`
- `requirements.txt`、`app/`、`tests/` 和 `evaluation/` 均存在。本阶段未修改这些模块。

### 工作目录规范

- 执行 Git 命令：`F:\srpTest\execution-diagnosis`
- 执行 CodePilot 的 `uv sync`、pytest、Ruff 等 Python 命令：`F:\srpTest\execution-diagnosis\codepilot\codepilot`
- 执行 SRP Python 命令：`F:\srpTest\execution-diagnosis\python_service`
- 不得从 `F:\srpTest` 直接执行本项目 Git 操作。
- `F:\srpTest\codepilot\codepilot_v2-master` 仍存在，但旧 `codepilot_v2-master` 仅作为备份，不再作为融合开发工作区；不得修改或同步融合代码到该目录。

### Ignore 与仓库卫生

- 根 `.gitignore` 已覆盖 SRP 的 `.env`、`.venv/`、`.pytest_cache/`、pytest fallback 缓存目录、`.ruff_cache/`、`.sandbox_tmp/`、`__pycache__/`、`*.pyc` 和 evaluation 运行结果。
- `codepilot/codepilot/.gitignore` 已覆盖 `.env`、`.venv/`、`uv.lock`、`.pytest_cache/`、`.ruff_cache/`、`.pico/`、构建产物及临时文件。
- `codepilot/.idea/` 与 `codepilot/.pico/` 中存在从上游导入的历史 tracked 文件，记为仓库卫生问题；Phase 0.5 不执行 `git rm` 或 `git rm --cached`。
- 未发现需要提交的 IDE 文件、运行输出、缓存或 Codex 临时文件。

### 职责边界

- CodePilot 负责 Agent Runtime、Tool Routing、Repo Search、File Read、Patch、Memory、Context Manager、Checkpoint 和后续 Repair Loop。
- SRP `python_service` 负责 Docker Sandbox、Compile/Run、Execution Feedback、Rule-first Classification、Root Cause Analysis、Evidence、`needRetrieval`、`retrievalQuery`、`repairSuggestion` 和 `AgentObservation`。
- 后续连接链固定为：`CodePilot → SrpClient → SRP FastAPI → Docker Sandbox → ErrorAnalyzer → AgentObservation → CodePilot 下一轮`。
- Rule-first 逻辑不得复制到 CodePilot。

Phase 0.5 未实现 `SrpClient`、`execute_and_diagnose`、`RepositoryExecution`、Repair Loop、Retrieval Hook 或任何 SWE-bench 集成。

## Phase 1 状态引用

Phase 1 在 `pico/integrations/srp_client.py` 建立了独立 SRP HTTP Client，
配置与失败边界见 `docs/srp_integration.md`。本阶段不修改 Agent Runtime，
不注册 `execute_and_diagnose` Tool，也不开始 Repair Loop 或 Retrieval。

## Phase 2 状态

Phase 2 通过 `pico/integrations/srp_provider.py` 注册可配置的
`execute_and_diagnose` Tool，并把精简的 SRP Observation 写入既有 history、
trace 和下一轮 prompt。仅在 `PICO_SRP_ENABLED=true` 时暴露该 Tool；本阶段
没有修改 AgentLoop 或 SRP ErrorAnalyzer，也没有实现自动 Repair Loop、
Retrieval、Repository Execution 或 SWE-bench。

Phase 2 验证结果：SrpClient `15 passed`、SRP Tool `24 passed`、AgentLoop
SRP 闭环 `1 passed`、核心 Runtime `10 passed`、CodePilot 全量
`188 passed, 12 failed, 6 warnings`、本阶段 Ruff `0 errors`、SRP 服务端
`8 passed`。12 个全量失败均属于既有冻结基线，没有新增 failure。真实 smoke
未执行，因为本机 `127.0.0.1:8080` 的 SRP ping 在 2 秒内不可用；这不影响
全 mock 通信和 AgentLoop 闭环验收。

## Phase 3 状态

Phase 3 在 `pico/repair_trajectory.py` 增加只负责观测的
`RepairTrajectory`，复用现有 AgentLoop、ToolExecutor、history、trace、
checkpoint、session 与 report。Runtime 没有增加错误类型到补丁的规则，也未
修改 AgentLoop；代码修改仍完全由模型决定。一次成功的代码修改后针对相同路径
执行 `execute_and_diagnose`，才构成一个 repair iteration。

诊断指纹由 execution status、failed stage、error type、error subtype 和
suspected location 组成，不包含自由文本 root cause。连续两次相同失败诊断会
记录 `repeated_diagnosis` 并提示模型重新评估。修复轮数默认上限为 3，由
`PICO_SRP_MAX_REPAIR_ROUNDS` 配置；第一版在达到上限时记录
`repair_round_limit` 并依赖既有 `max_steps` finalization，不直接终止 Runtime。

状态随 session 保存、进入 checkpoint，并在 `report.json` 的
`repair_summary` 中汇总完整 trajectory、diagnosis transitions、最终执行状态、
基础设施失败与 retrieval 信号。SRP unavailable 不计作代码诊断；
`needRetrieval` 只记录，不触发 Retrieval。

Phase 3 新增专项测试 `11 passed`；SrpClient `15 passed`、SRP Tool
`24 passed`、Phase 2 AgentLoop integration `1 passed`、核心 Runtime
`10 passed`，均无回归。CodePilot 全量为
`199 passed, 12 failed, 6 warnings`，通过数较 Phase 2 增加 11，失败仍为同一组
冻结基线问题；Phase 3 修改文件 Ruff `0 errors`，SRP 服务端 `8 passed`。

真实 smoke 已确认 SRP FastAPI 可启动，直接 ping 与 `SrpClient.ping()` 均成功。
Docker Desktop daemon 不可用，因此真实代码执行记为
`REAL_SMOKE_BLOCKED_BY_DOCKER`，真实模型修复闭环记为
`REAL_REPAIR_SMOKE_BLOCKED`；未修改 SRP 业务逻辑。Phase 3 未实现 Retrieval、
Repository Execution、worktree 或 SWE-bench，也未开始 Phase 4。

## Phase 4.1 状态

Phase 4.1 在 SRP Server 冻结独立的 Repository Execution Contract：新增
`RepositoryExecutionRequest`、`RepositoryExecution`、
`RepositoryObservation`、`RepositoryTestSummary`、
`RepositoryTestFailure` 和 `RepositoryExecuteAndAnalyzeResult`，并提供
`POST /api/execute-repository`。当前合法请求按设计返回 HTTP 501；非法
timeout、空路径或非 `pytest` runner 返回 422。

本阶段 endpoint 不读取 `workspacePath`，不复制 snapshot，不执行 pytest、
Maven 或 repository Docker，也没有 arbitrary command 字段。抽象
`RepositoryRunner` 仅作为后续扩展点；CodePilot Runtime、RepairTrajectory、
SrpClient、SrpToolProvider 和 ErrorAnalyzer 均未修改。

同时修正单文件 DockerSandbox preflight：`docker --version` 验证 CLI 后，
必须再由 `docker info` 验证 daemon。任一步失败都在编译/运行前返回
`ENVIRONMENT_ERROR / PRE_CHECK`，不会再被误报为 `COMPILE_ERROR`。

Phase 4.1 新增 Repository Schema、API Contract 与 Docker preflight 专项测试，
共 `19 passed`；SRP 全量由 8 增至 `27 passed, 1 warning`。CodePilot 关键回归
`61 passed`，全量仍为 `199 passed, 12 failed, 6 warnings`，12 项均为冻结的
已知失败。完整协议见根目录 `docs/repository_execution_contract.md`。Phase 4.1
未开始 Snapshot、Repository Runner、Repository Tool、Maven 或 SWE-bench。

## Phase 4.2 状态

Phase 4.2 在 SRP Server 新增 `RepositoryWorkspaceManager` 和内部
`RepositorySnapshot`。服务端配置 `REPOSITORY_ALLOWED_ROOT` 默认留空，未配置
时拒绝 Snapshot；相对路径只按 allowed root 解释，allowed root 与 workspace
都经过 absolute/canonical resolution，并使用路径组件关系阻止 `..`、不同磁盘
和 allowed root 外路径。

Snapshot 前及受控复制过程中均检查 symlink、Windows junction 和 reparse point，
不跟随链接。Snapshot 默认位于系统临时目录的
`srp_repository_snapshots/repo_<uuid>`，不会位于 source workspace 内；固定排除
`.git`、虚拟环境、依赖、构建、缓存、IDE 和 `.pico` 目录，但保留 `src/`、
`tests/` 与项目清单。

`snapshot_workspace()` 在正常及异常退出时清理；Cleanup 只删除同一 manager
登记且位于其 snapshot root 直属位置的目录，拒绝 source 或外部目录。隔离测试
证明修改或删除 Snapshot 文件不会影响 Original Workspace。本阶段不宣称解决
恶意并发文件系统变更的完整 TOCTOU 问题。

Phase 4.2 Workspace/Snapshot 专项测试 `24 passed`。本阶段没有实现 Repository
Runner、pytest/Docker repository execution、Repository Tool、Diagnosis 或
SWE-bench；`POST /api/execute-repository` 继续按设计返回 HTTP 501。Phase 4.1
Contract 回归 `19 passed, 1 warning`，SRP 全量为 `51 passed, 1 warning`，
Phase 4.2 修改文件 Ruff `0 errors`。CodePilot 关键回归 `61 passed`，全量仍为
`199 passed, 12 failed, 6 warnings`；12 项均为冻结的已知失败，没有新增回归。
