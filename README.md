# SRPAgent-Test-Demo01 · B 组执行反馈与诊断模块

本项目是“面向可靠代码生成的多模块协同和闭环优化系统”的 B 组实现，为生成代码提供静态检查、受控执行结果和错误诊断，供其他模块决定后续检索与修复。

当前团队接入版本为 **`srp-b-local 0.3.0`**，对应架构 v0.3、共同框架 v0.2.1、公共 `schema_version=2.0`。公开工厂入口为 **`srp_b:create_module`**，由 O 通过同进程 LocalTransport 调用；`/api/v2/*` 是逻辑能力标识。详细契约和交付边界见 [本地 v2 接入说明](docs/local_v2_handoff.md)。

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

当前 v2 诊断复用已有规则提取器，模型与检索调用均为零。M1 支持 Python 单文件标准库任务、内联制品、固定 pytest 测试和同步调用；不在该范围内的能力以实际能力声明和阻塞结果为准。

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

`requirements-local-v2.lock` 记录已验证的 Windows / Python 3.12 主应用依赖；沙箱依赖单独固定。本地入口不需要模型 API Key。

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
# 核对公共样例、契约和已登记源码哈希，不执行目标代码。
& '.\.venv-local-v2\Scripts\python.exe' -B scripts/check_local_v2.py

# 本地适配回归使用合成执行后端，不启动真实沙箱。
& '.\.venv-local-v2\Scripts\python.exe' -m pytest tests/test_local_v2.py -q
```

2026-10-16 的交付记录包含 33 项本地适配测试、15 项真实 Docker 验证和真实 B + A/C Mock 的混合流程。具体环境、源码哈希和覆盖范围见 [执行验证摘要](docs/verification/local_v2_validation.json) 与 [回归测试摘要](docs/verification/local_v2_tests.json)。该记录不代表全真实 A/B/C 联调完成或算法收益已验证；换机与更换镜像后应重新核验实际运行环境。

显式运行真实沙箱验证的方法见 [交付说明](docs/local_v2_handoff.md)。原始日志和私有状态保存在 `.interop/`，不提交到 Git。

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
