# B 组 MCP 接入说明

日期：2026-10-10。实现使用官方 Python SDK `mcp==2.3.0`，不手写握手或 JSON-RPC 编解码。HTTP 和 stdio 工具共用已有 v1 业务数据契约；HTTP 在进程内调用 DiagnosisService，独立 stdio 桥接器调用同一 B 组 REST 服务，不再启动自己的执行器或打开任务数据库。

## 1 接入方式

| 入口 | 适用方 | 生命周期 |
| --- | --- | --- |
| `http://127.0.0.1:8000/mcp` | 官方 SDK、远程 MCP 工具宿主 | Streamable HTTP，默认无协议级会话，返回 JSON |
| `python -m app.adapters.mcp.stdio` | 当前 CodePilot 等本地工具宿主 | SDK 管理 stdio；2025 版本使用 initialize/initialized |

HTTP 已验证协议版本 `2025-03-26`、`2025-06-18`、`2025-11-25`、`2026-07-28`。stdio 由 SDK 支持 `2024-11-05` 至 `2026-07-28`；本次直接验证了 CodePilot 的 `2025-06-18` 及官方 SDK 的旧握手和现代协议。

新版 `2026-07-28` 不使用旧 initialize 握手：每次调用携带 `_meta` 中的协议版本、clientInfo、clientCapabilities，并在 HTTP 头中镜像协议版本、方法名和必要的工具名。旧版按对应 SDK 协商握手；不要把两种外层格式混用。[当前规范](https://modelcontextprotocol.io/specification/2026-07-28)、[官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)

## 2 工具和结果

| 工具 | 关键输入 | 输出 |
| --- | --- | --- |
| `diagnose_error` | DiagnosticRequest，operation 同名，包含 EXTERNAL feedback | DiagnosticResult |
| `execute_and_diagnose` | DiagnosticRequest，包含非空 STDIO tests | DiagnosticResult |
| `check_syntax` | DiagnosticRequest，不含 tests/feedback | DiagnosticResult，语法成功仍需 RUN_TESTS |

`tools/list` 发布 inputSchema/outputSchema。工具 arguments 就是 DiagnosticRequest 本身，不加 request 包装；operation 必须与工具名一致。代码路径、长度、版本、摘要、测试冻结及报告引用均遵循原接入文档，不支持自由文本转命令、任意 URL 下载、仓库路径或依赖安装。

正常结果同时包含 `structuredContent=DiagnosticResult` 和一项等价 JSON 文本 `content`。前者供结构化客户端读取；后者兼容当前 CodePilot 的文本工具结果处理。发现代码错误时 `isError=false`，调用方仍应读取 execution.status、diagnosis 和 nextAction。

基础设施不能完成工作时 `isError=true`：取得结构化环境失败反馈时仍返回 DiagnosticResult；服务关闭、后端禁用、版本冲突或网络故障只返回含 ApiError 的 JSON 文本，不将错误包络伪装成符合 outputSchema 的正常结果。未知工具、参数结构错误和 operation 不匹配使用协议 INVALID_PARAMS；无效方法使用 SDK 的 METHOD_NOT_FOUND。

信息不足是正常业务结果 `nextAction=PROVIDE_CONTEXT`，不是 MCP 的 MRTR input_required。本版不发布 MCP tasks、sampling、elicitation、resources、prompts 或 subscriptions。长任务建议使用已有 A2A 提交/查询流程。

## 3 HTTP 调用

先按主接入说明启动 B 组服务。示例文件是 `docs/contracts/v1/mcp-list-tools.json` 和 `mcp-call-tool.json`：

```powershell
curl.exe -X POST http://127.0.0.1:8000/mcp `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: tools/list" `
  --data-binary "@../docs/contracts/v1/mcp-list-tools.json"

curl.exe -X POST http://127.0.0.1:8000/mcp `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -H "MCP-Protocol-Version: 2026-07-28" `
  -H "Mcp-Method: tools/call" -H "Mcp-Name: diagnose_error" `
  --data-binary "@../docs/contracts/v1/mcp-call-tool.json"
```

配置了 `INTEROP_API_TOKEN` 时增加 Authorization Bearer 请求头。直接调用 /mcp 会返回协议消息，不是浏览器页面；Swagger 页面仍在 /docs。

官方 SDK 客户端示例：

```python
import json
import os
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def diagnose():
    payload = json.loads(Path("../docs/contracts/v1/diagnose-request.json").read_text(encoding="utf-8"))
    token = os.environ.get("B_AGENT_API_TOKEN", "")
    headers = {"Authorization": "Bearer " + token} if token else {}
    async with httpx2.AsyncClient(headers=headers, timeout=300, trust_env=False) as http:
        transport = streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http)
        async with Client(transport, cache=None, read_timeout_seconds=300) as client:
            tools = await client.list_tools()
            result = await client.call_tool("diagnose_error", payload)
            return result.is_error, result.structured_content
```

这是 async 函数，调用方用自己的事件循环执行。SDK 自动协商并编码元数据，不需要应用手写新版 HTTP 头和握手。

## 4 当前 CodePilot

在 `python_service` 目录生成本机配置：

```powershell
.\.venv\Scripts\python.exe -m app.adapters.mcp.codepilot_config
```

生成 `.interop/codepilot-mcp.json`，包含当前 Python 解释器的绝对路径和固定 service cwd，不包含 token 或模型 Key。文件已存在时不会覆盖，可以通过 `--output` 指定另一个文件。跨机器 B 服务通过 `--url https://实际服务地址` 生成配置；源码仍内联传输，本地 bridge 只是 MCP 到 REST 的适配器。

CodePilot 启动时显式传入 `--mcp-config` 和这个配置文件的绝对路径。不会自动读取或修改项目现有 `.pico` 配置。工具名为 `mcp.srp_b.diagnose_error`、`mcp.srp_b.execute_and_diagnose` 和 `mcp.srp_b.check_syntax`。

需要凭证时由工具宿主进程继承 `B_AGENT_API_TOKEN`，或使用桥接进程工作目录中已有的 INTEROP_API_TOKEN 配置。不能把凭证放进 command、URL、项目 JSON 或工具 arguments。生成配置没有把这些工具标成 read_only：诊断也会记录版本/报告，并可能调用模型，CodePilot 的现有确认机制继续生效。

桥接器命令可独立查看：

```powershell
.\.venv\Scripts\python.exe -m app.adapters.mcp.stdio --url http://127.0.0.1:8000
```

启动后等待宿主发送 stdio MCP 消息，stdout 只用于协议，不是交互式终端。无需另启动一份 B 组数据库服务。

## 5 限制与安全

- HTTP 入口沿用共享 Bearer token；无 token 时只接受回环调用。当前未实现 MCP OAuth 资源元数据及授权服务器自动发现，宿主需显式提供凭证，不宣称具备完整 OAuth 集成。
- HTTP 开启 SDK 的 Host/Origin 校验。跨机器部署必须设置 INTEROP_PUBLIC_URL 为外部可达的 HTTPS origin，并正确转发 Host；不同 Web Origin 暂不接受，不要为了联调关闭重绑定保护。
- HTTP 请求和工具 arguments 限制为 1 MiB。stdio 桥接器只接受配置中的固定 HTTPS 服务 origin，回环可用 HTTP；不跟随重定向，不继承环境代理，不允许工具入参改变上游地址。
- MCP 默认两个工作线程，MCP_WORKERS 可配置 1..8；没有无界等待队列，满载返回 SERVICE_BUSY 工具错误。与 REST/A2A 的工作槽位分别限制，不是全服务统一并发上限。
- 请求取消或客户端断开不保证同步沙箱/模型工作立即停止。线程仍工作时保留并发槽位；关闭服务等待其结束，不能宣称已强制停止用户程序。
- stdio 上游 HTTP 等待默认 300 秒，可设 1..300。超时后返回 UPSTREAM_TIMEOUT，说明服务可能仍在工作，绝不自动重新执行。同 requestId 也不提供幂等保证。
- 跨组、跨机器的真实联调尚未完成；本次测试只验证协议互通和固定的可信源码样例，不替代生产隔离、Docker 验收或真实模型连通性验收。

## 6 模拟修复闭环

提供可运行的消费者，模拟生成/修复模块，真实调用 B 组服务。先提交加法题的错误减法实现，收到诊断，再以新 revision 和 previousReportId 提交固定修复；测试集、期望输出和测试摘要不变。固定修复代码不是另两个组的实际 Agent，也不是模型自动修复能力。

```powershell
.\.venv\Scripts\python.exe -m app.clients.integration_demo --protocol rest
.\.venv\Scripts\python.exe -m app.clients.integration_demo --protocol a2a
.\.venv\Scripts\python.exe -m app.clients.integration_demo --protocol mcp
```

每次生成独立 workflowId。A2A 使用真实异步提交、查询和同 contextId 的新修复任务；其他入口使用同一个业务契约。输出标记 mockAgents=true，并验证两次摘要关系和原有两个测试都通过。示例需要 Docker 就绪，或在可信本机开发服务显式启用 LocalSandbox；不会替你修改 .env。

测试位于 `python_service/tests/test_mcp_interop.py`，包括官方客户端、实际 CodePilot 最小客户端、真实 stdio 子进程、临时 HTTP 服务、鉴权/Host/Origin/大小限制、协议版本及错误映射、取消后工作槽位、三种协议的修复闭环。本轮新增 27 项测试；完整回归 182 项通过，3 项 Docker 验收因未启用环境而跳过。
