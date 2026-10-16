# B 组：静态检查、执行事实与诊断

当前共同集成基线为架构 v0.3、框架 v0.2.1、公共 `schema_version=2.0`。B 的正式接入入口为 **`srp_b:create_module`**，通过同进程 LocalTransport 调用。实现位于 [python_service/srp_b](python_service/srp_b)，交付说明见 [本地 v2 接入与验证](docs/local_v2_handoff.md)。

| 组别 | 当前职责 |
|---|---|
| A | 生成初版和修复候选 |
| B | 静态检查、独立沙箱执行事实、基于已有事实的诊断 |
| C | 检索决策、检索与证据评估 |
| O | 调度、完整上下文、授权预算、固定测试、隐藏验收和运行状态 |

B 的检索建议用于 C 的决策输入。实际检索、修复候选和全局状态由相应组产出。

当前版本 `srp-b-local 0.3.0` 提供三项本地能力，诊断复用既有真实规则层，模型和检索调用均为零；真实目标代码进入独立 Docker 容器。M1 范围为 Python 单文件标准库代码、内联制品、固定 pytest 测试和同步调用。

已有 Java、REST/A2A/MCP、仓库评测能力继续保留，按 [旧协议接入说明](docs/agent_interoperability.md) 使用。它们有各自的 v1 对象与摘要语义；共同 O 使用 v2 本地入口。

本次验证范围和实际结果见 [验证摘要](docs/verification/local_v2_validation.json)。该记录包含真实 B 与 A/C Mock 的本地混合流程；全真实 A/B/C 联调和算法收益实验由后续联合验证提供证据。
