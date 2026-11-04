# B Local v2：Claude 官方 SDK 接入

更新日期：2026-11-02，Asia/Shanghai。当前开发候选为 `srp-b-local 0.4.0`，公共 schema 2.0、三项 operation 和两个诊断模式不变。新增可选 `anthropic` 诊断后端，使用官方 `anthropic.Anthropic` SDK。默认仍为 `rules`；安装、能力发现、静态检查和沙箱执行都不会调用模型。

这是本地功能变更。此前发布的 0.3.1/P2 固定提交、清单和运行证据保留原样，不能作为 0.4.0 的验证或签收。真实 Claude API、真实 A/C、O 正式接收及算法收益需另行记录。

## 安装与配置

先按项目 README 安装共同框架，再从 B 的 `python_service` 目录执行：

```powershell
& '.\.venv-local-v2\Scripts\python.exe' -m pip install -c requirements-local-v2-anthropic.lock -e '.[test,anthropic]'
```

本次 SDK 约束为 `anthropic>=1.17,<2`；可复现环境约束记录了实际验证的 `anthropic==1.17.0`。规则模式只需要原有基础依赖。

密钥由部署者注入进程环境变量 `ANTHROPIC_API_KEY`，代码不会自动加载 `.env`。密钥不写进运行 JSON、能力声明、提示、公开响应或 Git；无需把密钥发送到聊天。模型 ID 必须显式选择账号已获授权的 Claude 模型，不根据演示名称推断可用性或上下文窗口。

```python
from srp_b import create_module

module = create_module(
    state_dir=".interop/claude/b-state",
    diagnosis_backend="anthropic",
    anthropic_model="REPLACE_WITH_APPROVED_CLAUDE_MODEL_ID",
    anthropic_max_tokens=1024,
    anthropic_timeout_seconds=30,
)
descriptor = module.capabilities()  # 不发网络请求
# response = module.call("/api/v2/diagnose", complete_request_envelope)
```

将示例中的模型占位符替换为实际模型 ID。O 使用 [完整 A/B/C 配置模板](integration/config.b-local.claude.example.json)，通过原 `build_transport` 加载；A/C 保持明确的 Mock 标记。配置中的 90 秒传输时限供两次串行 SDK 请求使用，实际仍受信封、授权、预算和 SDK 各自时限约束；O 应在运行前锁定本次配置与授权政策。

| 工厂参数 | 默认值 / 作用 |
|---|---|
| `diagnosis_backend` | `rules`；设为 `anthropic` 才启用 SDK |
| `anthropic_model` | 无默认模型；启用 SDK 时必须填写 |
| `anthropic_max_tokens` | 1024；单次生成上限，实际取配置与 CallGrant 输出限额的较小值，配置范围 1—8192 |
| `anthropic_timeout_seconds` | 30；每个 SDK 请求的超时，实际取剩余授权/预算时间的较小值，上限 120 秒 |
| `anthropic_api_key_env` | `ANTHROPIC_API_KEY`；只接受环境变量名称 |
| `anthropic_base_url` | 显式默认 `https://api.anthropic.com`；可配置团队批准的 HTTPS 网关，URL 不允许内嵌凭据、查询参数或 fragment |

SDK 的隐式 `ANTHROPIC_BASE_URL` 不参与选择，端点通过上述配置明确锁定。不存在凭据时返回 `ANTHROPIC_API_KEY_MISSING`；未安装可选 SDK 时返回 `ANTHROPIC_SDK_NOT_INSTALLED`。工厂和 `capabilities()` 不验证远端凭据或模型可用性。

## 诊断与授权边界

1. 仍先通过公共契约、可见性、身份、哈希、固定测试和引用权限检查，再提取规则事实。模型只解释已有公开证据，不执行代码、不调用工具、不检索、不修改原事实。
2. 两种诊断模式均可使用 SDK。没有失败假设/可引用证据时直接保留规则结果，不请求模型、不编造假设。
3. 有证据时，先要求 `max_model_calls>=1`、`max_rounds>=1` 和正数输入/输出授权。再通过 SDK `messages.count_tokens` 对实际发送的系统提示与完整上下文做预检，超出输入授权就阻塞。计数接口不生成文本，不计入推理调用次数。
4. 输入包含本能力的任务、当前代码、固定公开测试、原始失败来源、执行环境、历史、已授权 prior 诊断和已解析日志。模型输出仅允许根因假设、建议及已有证据索引；分类、父关系、测试、执行事实、下一动作等不由模型重写。
5. SDK `max_retries=0`，一次诊断最多提交一次推理请求；预检后重新核对期限。同步调用不能强制中断已在服务端开始的推理，迟到结果由原 O/LocalTransport 保留用量并处理。
6. 不请求工具、流式生成、显式缓存或模型思维链；SDK OpenTelemetry 被显式关闭，避免环境配置把提示或响应自动送入追踪系统。

`count_tokens` 是服务端预检，不替代返回的实际用量。若最终用量超过授权，返回 `ANTHROPIC_PROVIDER_EXCEEDED_GRANT` 并保留实际数值，交给 O 按现有账本处理，不截小用量以通过守卫。

## 用量、失败与重放

- 成功或已收到完整模型响应时，推理次数为 1；输入用量为服务端 `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`，输出使用服务端 `output_tokens`。未采集价格保持 `estimated_cost_usd=null`。
- HTTP 400/401/403/404/413/422/429 的明确拒绝按未执行推理记录；408、5xx、连接/读取超时等不明确结果保留未知模型/词元用量，让 O 保留预约。SDK 异常正文和服务端错误正文不回显。
- 截断、拒答、无效 JSON、越界/虚构证据索引、返回用量不完整都会产生稳定错误；已知用量照实记录，原失败事实保留为 `partial_result_ref`。不会把付费或未知结果静默写成零消耗规则成功。
- 相同调用的完成响应（包括错误）通过 SQLite 原样重放，保留同一个 `usage_id`，不再次计数或调用模型。跨重启 pending 诊断保留未知模型用量，即使新实例切回规则模式也不自动重做。
- 私有 SQLite 的 `model_observations` 表保留实际提示、计数、模型响应及阶段，关联 `call_id`；该表不通过公共制品解析器暴露，也不提交 Git。部署者继续负责状态目录访问权限。
- `final_hidden`、`final_acceptance`、restricted 反馈仍在 SDK 调用前拒绝进入公开诊断。

规则模式是显式配置选项：将 `diagnosis_backend` 设为 `rules`。修改配置后应使用新的运行/调用身份；既有调用按原记录重放，不能换配置自动重试不明请求。

## 验证与历史证据

新增测试使用真实 SDK 和内存 HTTP transport，覆盖两种模式、原 O 加载与多轮历史、授权/计数、实际用量与缓存词元、异常、保护视图、幂等、未知状态和 O 账本；不发真实 Claude 请求。当前测试结果见 [验证记录](verification/claude_sdk_validation.json)。

```powershell
& '.\.venv-local-v2\Scripts\python.exe' -B -m pytest tests/test_local_v2_claude.py tests/test_local_v2.py tests/test_local_v2_samples.py tests/test_local_v2_p2_lineage.py tests/test_local_v2_p2_boundaries.py tests/test_local_v2_p2_protected.py -q -p no:cacheprovider
```

`check_local_v2.py`、`check_p2_delivery.py` 和 P2 bootstrap/delivery 测试校验的是已发布 0.3.1 的精确字节快照，应在其固定提交执行；在修改后的 0.4.0 工作区拒绝旧摘要是预期保护行为。本次不重新生成或覆盖 0.3.1 的历史清单、样例、测试数量或正式验收状态。新版本仍需锁定源码、实际模型/环境和运行配置后，进行有凭据的真实 API 接收验证。

官方参考：[Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)、[Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)。
