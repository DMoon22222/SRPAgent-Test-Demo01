# B 本地模块 v0.3.1 候选交付

本次更新：2026-10-24，Asia/Shanghai。公共契约保持 schema 2.0，未修改共同 OpenAPI、守卫或 O 调度实现。参考共同基线 commit `55e9f3a945d58df60bd59ab8c57f206e3ebb67bd`，公共 OpenAPI SHA-256 为 `07382d82cce2c748b39110b6107575acc87af2ed86e15abaddd208f84b8aceae`。本轮 0.3.1 源码已固定至 `b/local-v2-adapter` 提交 `c1f52e8ed321616a8e364c1d43c22568c27fe17c`，15 份源码与测试时的工作区快照原始字节一致；验证记录中的基准提交及当时工作区状态保留其历史含义，不改写为提交后重跑。固定版本核对见 [记录](verification/local_v2_publication.json)，原实现 `ebb9406` 保持为历史版本。详细变更、验收及待签收状态见 [P1 报告](p1_delivery_review_20261024.md)。

## 安装与入口

主应用 Python >=3.11。先安装共同框架，再安装本组模块；本地包名为 `srp-b-local`，工厂为 `srp_b:create_module`。主应用仅导入公开入口，通过 JSON 兼容副本交接业务信封。

当前工作区安装示例，在 `F:\srpTest\execution-diagnosis\python_service` 执行：

```powershell
python -m venv .venv-local-v2
& '.\.venv-local-v2\Scripts\python.exe' -m pip install -c requirements-local-v2.lock -e 'F:/srpTest/reliable_codegen_framework' -e '.[test]'
```

`requirements-local-v2.lock` 记录本次实际验证的 Windows/Python 3.12 主应用依赖；执行沙箱依赖单独固定。本地模块不导入 FastAPI、A2A、MCP 或模型 SDK，旧服务沿用自身环境和 requirements.txt。

工厂接受三个 JSON 配置参数：`state_dir`（私有持久化目录，默认 `.interop/local-v2`）、`image`（默认 `srp-b-python:0.3.0`）、`max_payload_bytes`（默认 2 MiB，按 UTF-8 字节计）。工厂不启动服务、容器或后台线程。

```python
from srp_b import create_module

module = create_module(state_dir="runs/b-state", image="srp-b-python:0.3.0")
descriptor = module.capabilities()
response_envelope = module.call(operation, request_envelope)
```

`call` 接收完整信封，请求 17 个、响应 16 个必需顶层键，结果 payload 固定包含 `status/data/error/usage/warnings`。公开能力发现使用独立 CapabilityDescriptor。

| operation | 行为与结果 |
|---|---|
| `/api/v2/validate/static` | 真实 AST 语法检查、入口与制品完整性检查，返回 StaticCheckReport；不执行目标代码 |
| `/api/v2/execute` | 根据固定代码、测试、BuildManifest 和 ExecutionPolicy 在 Docker 执行，返回 ExecutionResult |
| `/api/v2/diagnose` | 支持 `static_feedback`、`feedback_only`，复用原始 failure_source，返回 DiagnosticResult；不重跑源码 |

当前诊断使用既有规则提取器，产出带证据指针的根因假设、上下文缺口和 `retrieval_hint/query_hints`。正式检索决策由 C 负责。`execute_then_diagnose` 不在此入口的能力声明中。

0.3.1 修复了日志来源引用：失败测试优先引用 `/test_case_results/<index>`，非空日志按真实来源引用 `/stdout` 或 `/stderr`，引用解析后仍保留流名称；不因合并分析文本而引用空 stderr。证据不足时不生成根因假设。`failure_source` 保持输入原文，诊断不重新执行代码。

未知静态检查返回 blocked 报告；缺少引用解析器、缺少诊断必需测试或不支持的任务范围明确阻塞。依赖、入口、哈希和上下文不通过时不执行目标。

## 独立沙箱与政策

从 B 仓库根构建部署镜像：

```powershell
docker build -t srp-b-python:0.3.0 -f docker/b-local/Dockerfile docker/b-local
```

部署 Dockerfile 使用 Python 3.11 和固定 pytest 8.3.5，在镜像构建阶段安装依赖。每次调用先解析本地镜像为不可变 image ID，探测实际 Python/pytest 版本，与 BuildManifest 比较；不匹配时返回真实环境故障且不启动目标。执行阶段不拉取镜像、不联网、不安装依赖。

本次重新使用本机已缓存的验证镜像，观察到 Python 3.11.5、pytest 8.3.5，未将部署 Dockerfile 描述为本次重新构建通过。该镜像在此前 Docker Hub 连接中断时通过已有基础镜像与固定离线 wheel 构建。其本次实际 image ID、Python/pytest 和验证范围保存在 [摘要](verification/local_v2_validation.json)。其他机器按部署 Dockerfile 构建后仍须重新验证实际环境。

受支持的政策为 `network_policy=disabled`、`root_read_only=true`、正数的 CPU/内存/PID/执行时间限制，以及规范相对 `allowed_write_paths`。写目录必须包含 `tmp`，不能覆盖代码、测试、支持文件或互相嵌套。网络 allowlist、任意 shell 命令及执行期安装依赖明确拒绝。

代码、测试和支持文件以只读工作区挂载；授权写目录使用有容量限制的 tmpfs，仅 JUnit 报告文件绑定到本次私有临时文件。报告按大小和文件类型检查，拒绝链接逃逸、XML DTD/实体；读取和导出均有边界。执行命令只允许经校验的 `python -m pytest <固定测试路径>`，附加参数由 B 构造。

容器使用非 root、关闭 capabilities、no-new-privileges 和请求资源限制。stdout/stderr 流式采集、限量保留，超出硬上限终止容器。目标执行超时、OOM、信号、政策拒绝与基础设施故障分别记录。每次调用清理唯一命名容器，记录是否确认清理；清理不明确时保留为基础设施故障。

ExecutionContext 保留原 manifest/policy 及规范 config hash，区分 requested/actual runtime。逐测试结果包含通过、失败、跳过和错误；未取得有效非空结果时不声明通过。主机记录墙钟时间，CPU 时间、峰值内存和费用未测项保持 null/unknown，未填写虚构值。

## 授权、版本、可见性和事实保留

- 每次新工作核验 CallGrant、BudgetSnapshot、调用身份及信封/授权/预算的最早截止时间。规则诊断不消费模型额度；执行必须有 execution_calls 授权。Usage 的模型、检索、执行次数真实计量，未知执行状态保留未知值。
- 按公共算法逐文件计算 UTF-8 SHA-256，再对按 path 排序的 path/sha256 数组计算集合哈希；支持文件和完整工作区校验复用共同公开守卫。保持代码版本不可变与 run 内 public/final_hidden 测试各自冻结。
- 私有 SQLite 日志保存调用指纹、完成信封和事实。同 operation/message_id 同内容返回原信封与同一 usage_id；不同内容拒绝。call_id 不能换 message_id 重复消费；跨重启 pending 返回 OUTCOME_UNKNOWN，不自动再执行。
- 执行与诊断是独立调用。诊断失败时保存原事实并返回 partial_result_ref；O 可从此前已登记的事实解析同一规范引用。`resolve_fact` 仅供本组手动恢复检查，主流程通过 O 的受控解析器交接。
- 本模块提供 `bind_artifact_resolver(resolver_or_none)`，仅在当前调用解析明确引用并核验原文哈希，调用结束解除绑定。缺失上下文不会用私有数据库替代。
- `final_hidden` 只随 restricted/final_acceptance 执行请求进入 B；公开诊断拒绝保护反馈，错误摘要不回显保护正文。真实保护结果留在私有日志和 O 受控记录。

`.interop/`、虚拟环境和原始运行记录不提交。部署者需对私有状态目录配置实际 OS 访问权限；同进程模块的信任边界与共同规范保持一致。

## 验证和共同接入

公开合成样例见 [local_samples.json](contracts/v2/local_samples.json)，11 个场景包含静态失败及诊断、执行通过/失败及诊断、运行环境不匹配、超时、授权不足、完成重放、保护反馈拒绝和诊断故障后的事实保留。每项标记真实工具／执行、故障注入或重放，保存实际响应。保护反馈拒绝用公开基础请求与两个标量修改描述被拒绝的合成请求，`sample_request(sample)` 可重建；不导出保护对象正文。重建后的非法请求必须被公共诊断 Schema/Guard 拒绝，其实际标准错误响应通过 TransportErrorResponse 校验，不能当成正常业务结果。日期和编号仅供结构复核，重新调用须刷新身份、期限并重算实际内容哈希。

```powershell
# B 的本地适配回归，使用新安装的主应用环境
& '.\.venv-local-v2\Scripts\python.exe' -m pytest tests/test_local_v2.py tests/test_local_v2_samples.py -q

# 适配、共同框架、旧 B 服务三组回归；实际 JUnit 数量进入公开摘要
& '.\.venv-local-v2\Scripts\python.exe' -B scripts/run_local_v2_tests.py

# 显式执行自建合成目标；原始记录只写 .interop/validation
& '.\.venv-local-v2\Scripts\python.exe' -B scripts/verify_local_v2.py --docker --output ../docs/verification/local_v2_validation.json --public-samples ../docs/contracts/v2/local_samples.json --framework-config ../../reliable_codegen_framework/config.b-local.example.json

# 所有材料生成后检查源码、样例与证据一致性
& '.\.venv-local-v2\Scripts\python.exe' -B scripts/check_local_v2.py
```

本机共同仓库 `b/local-v2-handoff`、提交 `d3f4674` 提供单独的 `config.b-local.example.json` 选择真实 B，其余 A/C 保留 Mock；该示例尚未进入远端 main。本次通过共同框架正式 `build_transport` 加载该配置，使用原 `adaptive_rag`、两次修复上限和 15 秒传输时限，仅覆盖 B 私有状态目录和显式选定镜像。真实 O 完成一次修复并进入 accepted，不能据此宣称真实 A/C 验证、O 配置签收或共同默认已切换。原 config.example.json 保持不变。

共同 `collaboration/groups/B.json`、`integration/services.json` 与 `modules/b/` 当前仍登记历史 0.3.0 固定提交。本轮未修改共同仓库；0.3.1 已有上述固定源码提交，待将新版本和本次证据更新到共同登记位置，并填写实际接收状态。分支上传及 PR 评审不等于共同登记完成或 O 签收。

实际回归数量与分支记录见 [验证摘要](verification/local_v2_validation.json) 和相邻测试摘要；UTC 时间戳对应本地 2026-10-24。CPU/峰值内存、A/C 真实模块、组间签收和算法收益未验证。轮子安装独立检查见 [wheel 摘要](verification/local_v2_wheel.json)。
