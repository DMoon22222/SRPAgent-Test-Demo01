# SRPAgent-Test-Demo01 · B 组执行反馈与诊断模块

本项目是“面向可靠代码生成的多模块协同和闭环优化系统”的 B 组实现，为生成代码提供静态检查、受控执行结果和错误诊断，供其他模块决定后续检索与修复。

当前开发候选为 **`srp-b-local 0.4.0`**，新增 [Claude 官方 SDK 可选诊断后端](docs/claude_sdk_integration.md)。已发布的 P1/P2 固定版本仍为 0.3.1，历史证据与本次新功能验证分开记录。项目对应架构 v0.3、共同框架 v0.2.1、公共 `schema_version=2.0`。公开工厂入口为 **`srp_b:create_module`**，由 O 通过同进程 LocalTransport 调用；`/api/v2/*` 是逻辑能力标识。原 0.3.1 交付见 [P1 报告](docs/p1_delivery_review_20261024.md)和[本地 v2 交付](docs/local_v2_handoff.md)。

共同框架最近的 B 0.4.0 登记资料已同步，入口见 [同步说明](docs/framework_sync_20261107.md)、[当前交付](docs/local_v2_handoff_v0.4.0.md)、[O 接收核对单](docs/integration/receiver_checklist_v0.4.0.md)及 [M1 原时点缺口报告](docs/m1_readiness_20261105.md)。同步保留原验证日期和待接收状态。

完整的职责边界、已实现功能、源码对应关系、验证范围及待办见 [B 组功能定位与当前项目已实现功能说明](docs/b_group_role_and_implemented_features.md)。

2026-11-07 的 B 组轻量加固结果见 [开发成果报告](docs/pre_integration_hardening_20261107.md)、[诊断评测](docs/verification/diagnosis_benchmark_20261107.md)和[组会汇报单页](docs/group_meeting_update_20261107.md)。其中真实 Docker 快速检查、固定事实评测与离线回归分别统计，尚未代表 O 正式接收。

上述验证快照的当前提交与推送状态见 [轻量加固发布绑定](docs/pre_integration_publication_20261107.md)，历史验证日期和结果保持原样。

## 主要功能

| 能力 | 逻辑操作 | 主要输出与行为 |
|---|---|---|
| 静态检查 | `/api/v2/validate/static` | 使用 AST 检查 Python 语法、入口及制品完整性，返回 `StaticCheckReport`，不运行目标代码 |
| 受控执行 | `/api/v2/execute` | 根据固定代码、测试、构建清单与执行政策，在独立 Docker 容器中运行 pytest，返回 `ExecutionResult` |
| 错误诊断 | `/api/v2/diagnose` | 支持 `static_feedback`、`feedback_only`，基于已有静态或执行事实返回 `DiagnosticResult`，包含根因假设、证据指针及检索建议 |

- **执行事实采集**：记录逐测试结果、限量 stdout/stderr、实际运行环境与墙钟时间，区分测试失败、超时、OOM、信号、政策拒绝和基础设施故障。
- **沙箱约束**：目标源码进入非 root、禁网且有资源限制的独立容器；代码与测试只读，授权写目录使用受限 tmpfs。执行时不安装依赖。
- **契约与授权校验**：保留完整 v2 消息信封，检查授权、预算、截止时间、制品哈希、代码版本和固定测试；受保护验收反馈按可见性约束交接。
- **持久化与重放**：私有 SQLite 日志保存事实及完成响应；相同调用重放返回原结果，未确认完成的执行保留未知状态，避免自动重复执行。

默认 v2 诊断复用已有规则提取器，模型与检索调用均为零。0.4.0 可显式配置 `diagnosis_backend="anthropic"`，通过官方 SDK 对已有公开证据生成根因假设和建议，并记录实际用量；安装配置及验证边界见 [Claude 接入说明](docs/claude_sdk_integration.md)。M1 支持 Python 单文件标准库任务、内联制品、固定 pytest 测试和同步调用；不在该范围内的能力以实际能力声明和阻塞结果为准。

## 团队职责

| 组别 | 职责 |
|---|---|
| A | 生成初版、测试候选和修复候选 |
| B（本项目） | 静态检查、独立沙箱执行事实、基于已有事实的诊断 |
| C | 检索决策、检索与证据评估 |
| O | 调度、完整上下文、授权预算、固定测试、隐藏验收和运行状态 |

B 输出的 `retrieval_hint/query_hints` 是 C 的决策输入；实际检索、修复候选和全局状态分别由对应模块负责。

## 快速开始：本地 v2 模块

需要 Python 3.11 或以上。真实执行另需支持 Linux 容器的 Docker；能力发现和下述只读资料检查无需启动沙箱。共同框架为私有仓库，安装者需具有相应访问权限。

以下 PowerShell 命令从本项目根目录执行，将共同框架克隆到相邻的 `reliable_codegen_framework` 目录，并锁定本次验证使用的基线。若已有框架副本，可直接使用对应路径。

```powershell
git clone https://github.com/H1Unter3/Collaborative_Reliable_CodeGen_Loop.git ../reliable_codegen_framework
git -C ../reliable_codegen_framework checkout 55e9f3a945d58df60bd59ab8c57f206e3ebb67bd

cd python_service
python -m venv .venv-local-v2
& '.\.venv-local-v2\Scripts\python.exe' -m pip install -c requirements-local-v2.lock -e '../../reliable_codegen_framework' -e '.[test]'
& '.\.venv-local-v2\Scripts\python.exe' -c 'from srp_b import create_module; print(create_module().capabilities())'
```

`requirements-local-v2.lock` 记录原有 Windows / Python 3.12 基础依赖；沙箱依赖单独固定。默认规则模式不需要模型 API Key。Claude 模式使用可选 `.[anthropic]` 依赖、独立约束 `requirements-local-v2-anthropic.lock`，并要求部署者注入密钥、选择实际模型和取得 O 调用授权。

在本项目根目录构建执行镜像：

```powershell
docker build -t srp-b-python:0.3.0 -f docker/b-local/Dockerfile docker/b-local
```

O 按 `module:factory` 加载入口；手动调用的形式为：

```python
from srp_b import create_module

module = create_module(state_dir=".interop/local-v2", image="srp-b-python:0.3.0")
descriptor = module.capabilities()
# operation 为上述逻辑操作，request_envelope 为包含授权、上下文和 payload 的完整信封。
# response_envelope = module.call(operation, request_envelope)
```

完整请求与响应见 [公开合成样例](docs/contracts/v2/local_samples.json)，能力声明见 [capabilities.json](docs/contracts/v2/capabilities.json)。样例中的身份和日期用于结构核对，重新调用时需刷新身份、期限并计算实际内容哈希。O 的混合配置及受控制品解析器接法见 [交付说明](docs/local_v2_handoff.md)。

## 验证

在 `python_service` 目录执行：

```powershell
# 在 0.3.1 固定提交核对其公共样例、契约和源码哈希；0.4.0 使用下述新测试。
& '.\.venv-local-v2\Scripts\python.exe' -B scripts/check_local_v2.py

# 本地适配回归使用合成执行后端，不启动真实沙箱。
& '.\.venv-local-v2\Scripts\python.exe' -m pytest tests/test_local_v2.py tests/test_local_v2_samples.py -q

# 安装可选依赖后验证 Claude 接入；使用 SDK 内存 HTTP transport，不请求真实模型。
& '.\.venv-local-v2\Scripts\python.exe' -m pytest tests/test_local_v2_claude.py -q
```

2026-10-24（Asia/Shanghai）的本次验证包含 46 项适配测试、99 项共同框架测试和 182 项旧 B 服务测试通过，另有 3 项旧版 Docker 冒烟测试跳过。执行验证程序的 17 项检查包括真实 Docker、规则诊断、显式故障注入和按共同本机交付配置加载的真实 B + A/C Mock 混合流程；11 个公开样例逐项注明来源。具体环境、源码哈希和覆盖范围见 [执行验证摘要](docs/verification/local_v2_validation.json) 与 [回归测试摘要](docs/verification/local_v2_tests.json)。0.3.1 源码已固定为提交 `c1f52e8ed321616a8e364c1d43c22568c27fe17c`，其原始字节与验证快照逐项一致，见 [固定版本核对记录](docs/verification/local_v2_publication.json)。O 正式签收、全真实 A/B/C 联调和算法收益仍待验证。

显式运行真实沙箱验证的方法见 [交付说明](docs/local_v2_handoff.md)。原始日志和私有状态保存在 `.interop/`，不提交到 Git。

P2 工具与公开证据已固定在提交 `b3239cadf26da6360862f84a6da80f10717e8dcc` 并推送到 `b/local-v2-adapter`，B runtime 保持 0.3.1。46 份文件的提交原始字节与交付清单一致，见 [发布记录](docs/verification/p2/publication.json) 和 [发布说明](docs/p2_publication_progress_20261026.md)；后续文档提交可继续推进分支，固定工具版本保持不变。

当前交付包含 [可移植配置](docs/integration/config.b-local.p2.example.json)、[运行基线清单](docs/integration/p2_handoff_manifest.json)、[交付文件摘要](docs/integration/p2_delivery_files.json) 及 [P2 汇总](docs/p2_handoff_20261030.md)。多轮历史、谱系、引用、预算重放、异常和保护接收视图均已有技术证据。105 项定向回归通过；真实 Docker/O 运行与合成后端测试分别记录，A/C 保留 Mock，正式 P2 仍待材料、消费意见及 O 独立接收。

[候选交付报告](docs/p2_delivery_progress_20261026.md) 记录了 66 条目的本地白名单归档及独立目录离线 wheel/静态接入烟测；该烟测未重新执行 Docker。可在 `python_service` 运行 `python -B scripts/check_p2_delivery.py` 核对快照。历史旁录保留组装时的未发布状态，当前发布事实以新增发布记录为准；原件和 ZIP 留在私有 `.interop/`。

## 目录与其他工具

| 位置 | 内容 |
|---|---|
| [python_service/srp_b/](python_service/srp_b/) | 当前 schema v2 本地模块、诊断、持久化日志和沙箱执行器 |
| [python_service/tests/test_local_v2.py](python_service/tests/test_local_v2.py) | 本地适配回归测试 |
| [python_service/scripts/](python_service/scripts/) | 资料一致性检查与真实沙箱验证脚本 |
| [docker/b-local/](docker/b-local/) | v2 受控执行镜像 |
| [docs/contracts/v2/](docs/contracts/v2/) | 公开能力声明和请求／响应样例 |
| [docs/verification/](docs/verification/) | 可公开的验证摘要 |
| [python_service/app/](python_service/app/) | 既有 Python 服务、执行与分析组件 |
| [src/](src/) | 既有 Java / Spring Boot 实现 |
| [codepilot/](codepilot/) | CodePilot 工具及接入资料 |
| [evaluation/swebench/](evaluation/swebench/) | SWE-bench 评测工具与说明 |

仓库保留原有 Java、Python FastAPI、REST/A2A/MCP 和仓库评测工具，使用方法见 [Python 服务说明](python_service/README.md)、[旧协议接入说明](docs/agent_interoperability.md) 和 [MCP 接入说明](docs/mcp_integration.md)。这些工具使用各自的 v1 对象与摘要语义；团队 O 当前通过上述 v2 本地入口接入 B。
