# B 组错误分析 Agent 接入说明

本版实现统一业务契约、REST/OpenAPI、A2A 1.0 JSON-RPC 和 MCP 工具入口。三个入口复用同一个 `DiagnosisService` 和规则优先分析器，独立 stdio 桥接器通过 REST 调用该服务。B 组负责诊断，不负责调用生成 Agent、修改代码、实际检索或控制全局修复循环。MCP 详细接入和模拟修复样例见 [MCP 接入说明](mcp_integration.md)。

## 1 启动

在 `python_service` 目录安装 `requirements.txt` 中的依赖，并运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

新增配置见 `python_service/.env.example`。A2A 官方 Python SDK 固定为 `a2a-sdk[http-server]==1.0.3`，协议协商版本为 `1.0`，不支持旧版 `message/send` 或带 `kind` 的 Part 格式。[官方 SDK](https://github.com/a2aproject/a2a-python)、[A2A 规范](https://a2a-protocol.org/v1.0.0/specification/)

必须使用一个 Uvicorn 进程。进程内默认两个 A2A 工作线程，最多 32 个待完成任务；REST 另有两个并发槽位，MCP 默认两个工作线程。SQLite 默认位于工作目录的 `.interop/tasks.sqlite3`，文件锁拒绝第二个进程同时使用同一任务库。部署目录应固定，不要在多个工作目录启动各自的数据副本。

默认执行后端仍沿用项目的 Docker 配置。新入口使用 LocalSandbox 必须显式设置 `INTEROP_ALLOW_LOCAL_EXECUTION=true`；LocalSandbox 没有隔离能力，仅供可信源码的本机开发使用。Docker 镜像的准备方式见现有 README。

## 2 REST 接口

| 接口 | 输入/输出 | 用途 |
| --- | --- | --- |
| `POST /api/v1/diagnose` | DiagnosticRequest / DiagnosticResult | 分析外部已有执行反馈，不执行源码 |
| `POST /api/v1/execute-and-diagnose` | DiagnosticRequest / DiagnosticResult | 执行固定 STDIO 测试集并诊断首个失败；保留全部失败用例反馈 |
| `POST /api/v1/check-syntax` | DiagnosticRequest / DiagnosticResult | 仅语法/编译检查 |
| `GET /api/v1/capabilities` | JSON | 能力、限制、协议与比较规则 |
| `GET /health/ready` | JSON | 服务与任务库就绪情况，执行后端状态单独报告 |
| `GET /docs`、`GET /openapi.json` | Swagger / OpenAPI | 可浏览接口与语言无关模型 |

首版只接受一个 `Main.py` 或 `Main.java` 源文件，内联传输源码；测试为非空 STDIO 用例集，最多 20 个。暂不接收远端仓库路径、压缩包、任意 URL、执行命令或依赖安装命令。请求体最多 1 MiB，源码最多 200000 字符，单个日志字段最多 12000 字符。

使用同一个 DiagnosticRequest 包络，`operation` 必须与路由一致。执行请求必须有 `tests`，诊断请求必须有 `source=EXTERNAL` 的 `feedback`，语法检查不能包含测试集。完整示例和 Schema 位于 `docs/contracts/v1/`。

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/diagnose `
  -H "Content-Type: application/json" `
  --data-binary "@../docs/contracts/v1/diagnose-request.json"
```

接收程序的错误反馈是正常业务结果，可以返回 HTTP 200。请求校验失败返回 422，代码/测试/报告引用冲突返回 409，服务繁忙或显式禁用的执行后端返回 503。错误包络为 `requestId, code, message, retryable, details`，不回显源码或 SDK 异常。参数校验错误可能尚无法取得 requestId。

## 3 数据和语义

- `workflowId` 是调用方的整体编程任务标识；`requestId` 是调用标识，不是幂等键。重试可能产生新报告或新 A2A Task，首版不保证自动去重。
- `producerAgentId` 仅用于业务关联，不用于认证。`iteration` 和 `previousReportId` 由外层流程填写；后者必须引用当前认证主体、同一工作流的已生成报告。
- 服务计算 `codeDigest`。摘要输入为包含 language、entryPoint 和按 path 排序的 files 的 JSON：键排序、无多余空白、UTF-8、`ensure_ascii=False`；保留源码原始换行和空白。artifactId/revision 不参与摘要。测试摘要覆盖 kind 与按原顺序排列的 cases，不包含 suiteId/revision/origin。
- 同一认证主体、工作流、artifactId、revision 对应的源码不可变化；修改源码必须升 revision。首次提交的测试集在该工作流中冻结，修复不能修改测试、用例顺序或期望值；变更测试需要新 workflowId。
- 外部反馈的代码引用必须匹配请求；提供 digest 时也必须匹配内容。请求同时携带测试集时检查测试引用和摘要。外部反馈不会被伪装成 B 组复现；没有摘要的反馈会增加明确警告。
- `expectedOutput` 必填，空字符串也会比较。比较规则沿用原有输出标准化：CRLF/CR 转 LF，去除两端空白，因此不是逐字节比较。测试执行数为零不能报告 STDIO 成功；仅语法成功返回 `RUN_TESTS`，不会返回 `ACCEPT`。
- `analysisMode` 区分实际有效的模型解释和规则降级；模型请求限制 30 秒，SDK 自动重试关闭。分类仍以规则为准。未配置模型不会导致基础诊断服务不就绪。
- 检索决策为 `REQUIRED / NOT_REQUIRED / UNDETERMINED`，只有 REQUIRED 携带检索 query。未知分类返回 `INSUFFICIENT_CONTEXT`，不会把未知映射成“不需要检索”。本版不执行检索。
- 证据区分执行、规则和模型来源。当前不推断可靠性不足的源码行号，`suspectedLocations` 可能为空；调用方不能假设每份报告都已有精确定位。
- `nextAction` 指导外层流程：`REPAIR`、`RETRIEVE_THEN_REPAIR`、`PROVIDE_CONTEXT`、`ACCEPT`、`RUN_TESTS`、`REVIEW_EXTERNAL_RESULT` 或 `FIX_ENVIRONMENT`。代码修复及全局终止判定由其他模块负责。

## 4 A2A 接口

能力发现：`GET /.well-known/agent-card.json`。AgentCard 的地址由 `INTEROP_PUBLIC_URL` 决定，跨机器部署时必须配置为调用方可达的 HTTPS 地址。

通信入口：`POST /a2a`，请求头 `Content-Type: application/json` 和 `A2A-Version: 1.0`。使用官方 SDK 处理 JSON-RPC 编解码、版本校验及标准错误。不宣称支持 A2A REST binding。

| 方法 | 行为 |
| --- | --- |
| `SendMessage` | 一个 ROLE_USER 消息，恰好一个 data Part，内容为 DiagnosticRequest |
| `GetTask` | 按服务生成的 Task.id 查询状态与结果 |
| `ListTasks` | 按当前主体查询，支持 contextId/status/statusTimestampAfter、分页、历史和 artifact 选择 |
| `CancelTask` | 仅取消排队或 INPUT_REQUIRED 的任务；运行中及终态返回 TaskNotCancelableError |

示例请求：`docs/contracts/v1/a2a-send-message.json`。`configuration.returnImmediately=true` 立即返回任务；默认 false 等待终态或 INPUT_REQUIRED。JSON-RPC `id` 仅关联单次 RPC 响应，不是 workflowId、requestId 或 Task.id。

```powershell
curl.exe -X POST http://127.0.0.1:8000/a2a `
  -H "Content-Type: application/json" -H "A2A-Version: 1.0" `
  --data-binary "@../docs/contracts/v1/a2a-send-message.json"
```

`SendMessage` 的结果是 `result.task`，查询参数为 `{ "id": "服务返回的 Task.id" }`。产物位于 `task.artifacts[].parts[].data`，内容仍是 DiagnosticResult，不需另学一套业务字段。

Python 官方 SDK 使用 Protobuf Value 承载 data，JSON 整数可能读成 `0.0`。本项目的 `data_to_contract(value, DiagnosticResult)` 会在严格模型校验前恢复可精确表示的整数；其他语言按 JSON Schema 的整数语义校验即可，不应把布尔值或数字字符串当作整数。

生命周期是 `TASK_STATE_SUBMITTED → TASK_STATE_WORKING → TASK_STATE_COMPLETED / FAILED / INPUT_REQUIRED`，排队和等待补充输入也可转 CANCELED。被分析程序出错不代表 B 组任务失败：产出了有效诊断就是 COMPLETED；无法执行所需工作或基础设施错误才是 FAILED。判定信息不足时是 INPUT_REQUIRED，并保留已有诊断产物。

为 INPUT_REQUIRED 的任务补充反馈时带 `taskId`，必须保留代码版本和 workflowId；终态不可重新启动。修复代码使用新 task，复用服务已认可的 contextId，并带新 revision 和 previousReportId。未知/不可访问的 contextId 被拒绝，不允许调用方任意认领。

任务及结果持久化，服务重启将未结束的 SUBMITTED/WORKING 标记 FAILED，并注明 SERVICE_RESTARTED，不盲目重跑源码。INPUT_REQUIRED 和既有终态保留。客户端断开不等于任务取消。历史最多保留十条消息，任务库暂未实现自动过期清理，部署方需安排备份、容量与保留策略。

不支持 `SendStreamingMessage`、`SubscribeToTask`、推送通知或扩展 AgentCard。AgentCard 不广告这些能力；调用分别得到标准 UnsupportedOperation、PushNotificationNotSupported 或 ExtendedAgentCardNotConfigured 错误。

## 5 安全和部署边界

无 `INTEROP_API_TOKEN` 时，新入口只接受回环地址；跨机器调用必须设置 token，并带 `Authorization: Bearer <token>`。AgentCard 和健康检查不包含密钥。HTTPS 由反向代理终止，不能通过明文公网传输 token。

首版只有一个共享 token，使用它的调用方属于同一认证主体，能够查询该主体的全部任务。这不是逐 Agent 的租户隔离；producerAgentId 不能改变权限。需要各组隔离时，下一阶段接入 JWT/OAuth 或独立服务账号。

旧 `/api/*` 的本机调用、数据格式和输出比较行为保持不变，远端调用被限制为新入口。反向代理只暴露新接口、`/mcp`、AgentCard 和所需文档，不能把本地可信仓库接口转发给远端。无 token 的本机开发服务也不能通过代理转成匿名公网服务。

SQLite 中可能包含源码、反馈和诊断，限制数据目录的 OS 权限。Docker 隔离仍依赖宿主、镜像和既有执行器配置；本次没有新增输出流硬限额、容器强制取消或完整执行器加固，API 输出截断不等于进程内存限制。

## 6 验证和后续

重新生成 Schema 和示例：`python -m app.contracts.export`。回归测试：`python -m pytest tests -q`。新增测试覆盖严格契约、摘要和引用冲突、测试冻结、检索三态、旧接口兼容、鉴权、任务分页与补充输入、排队取消、重启恢复和官方 SDK 客户端调用。

2026-10-09 本次验证结果：155 项通过，3 项真实 Docker 验收测试因未启用 `RUN_REPOSITORY_DOCKER_SMOKE=1` 而跳过。已验证可信本地 Python 执行与官方 A2A SDK 的 ASGI 客户端调用；未做真实远程模型连通性验证，也未与其他两组实机联调。

2026-10-10 已补充 MCP HTTP/stdio 接入，以及 REST/A2A/MCP 三种协议的模拟生成、诊断、修复和复测闭环。完整回归结果：182 项通过，3 项真实 Docker 验收测试仍因未启用环境而跳过。现有 CodePilot 通过 stdio-to-REST 桥接器接入，不要求其升级为远程新版 MCP 客户端。

目前不包含：远程仓库工件上传、A2A SSE/Webhook、运行中强制取消、消息去重、多进程任务调度、MCP OAuth 自动接入及三组真实联调。模拟生成/修复模块并非另外两组真实 Agent。
