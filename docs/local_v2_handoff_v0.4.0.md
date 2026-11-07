# B 0.4.0 固定候选交付（待联合接收）

> 同步日期：2026-11-07（Asia/Shanghai）；来源为共同框架固定提交 [`5ecb03c`](https://github.com/H1Unter3/Collaborative_Reliable_CodeGen_Loop/blob/5ecb03c3c6a6ab0878657cd9ba3bd8ee71990014/modules/b/handoff_v0.4.0.md)。正文保留 2026-11-04 的准备/登记时点，仅适配本仓库链接；其中验收前及 11 月 5 日的安排属于当时计划。此同步未新增模型、Docker 或目标代码运行，也未补写接收结论。

登记日期：2026-11-04，Asia/Shanghai。公开工厂为 `srp_b:create_module`，公共 schema 2.0、三项业务操作与两个诊断模式不变。最新候选新增官方 Anthropic Python SDK 可选诊断；默认 `rules`。本登记是候选共享与证据索引，尚无 O 正式接收。

| 项目 | 固定内容与实际范围 |
|---|---|
| B 版本 / 实现提交 | `srp-b-local 0.4.0` / `c5e04a4ab2f9d80b98439e42228cc3515e0b0534` |
| B 源码 | [固定提交](https://github.com/DMoon22222/SRPAgent-Test-Demo01/tree/c5e04a4ab2f9d80b98439e42228cc3515e0b0534)；[评审 PR](https://github.com/DMoon22222/SRPAgent-Test-Demo01/pull/1) |
| 共同运行基线 | 框架 0.2.1、架构 0.3；固定 `55e9f3a945d58df60bd59ab8c57f206e3ebb67bd` |
| 入口 / 传输 | `srp_b:create_module` / 同进程 LocalTransport；目标源码仍交独立 Docker |
| 0.4.0 已验证 | 11 月 2 日：132 项 B 测试（含 44 项 SDK 内存 HTTP）、99 项共同框架；依赖安装及 wheel 独立解压加载，复用既有依赖 |
| 11 月 4 日核对 | 26 份源码与已推送 Git 对象一致；另生成真实 AST/规则公开样例，未调用模型或执行目标 |
| 仍待验证 | 真实 Claude 账号/模型/API、0.4.0 新 Docker 运行、干净依赖安装、O 独立接收、真实 A/C 全链 |
| 历史稳定入口 | 0.3.1 接入 `145bc77a271ac2efb22fc7e159090fe605f72602`，工具 `b3239cadf26da6360862f84a6da80f10717e8dcc` |

## 获取、安装与选择模式

接收方需要这两个私有仓库的访问权限。在自己的接收目录克隆 B 与共同框架并 checkout 上表的固定实现/运行基线。进入 B 的 `python_service`，先在兼容 Python >=3.11 的环境安装固定共同框架，再安装本组包：

```powershell
# rules 模式：基础依赖即可
python -m pip install -c requirements-local-v2.lock -e '.[test]'

# anthropic 模式：可选依赖与本次验证的SDK约束
python -m pip install -c requirements-local-v2-anthropic.lock -e '.[test,anthropic]'
```

规则模式用 [0.4.0 配置](integration/config.b-local.v0.4.0.example.json)；SDK 模式用 [Claude 配置模板](integration/config.b-local.claude.example.json)。新配置随本 B 登记 PR 提供，不假定原 55e9f3a 基线已含这些文件；取得后记录配置 SHA-256。A/C 仍为明确的 Mock，默认共同 `config.example.json` 保持原样。

SDK 模式必须将模型占位符替换为账号实际获授权的模型 ID，在本机进程环境注入 `ANTHROPIC_API_KEY`；配置不放密钥值。默认明确使用官方端点，团队批准的网关通过 `anthropic_base_url` 显式配置。模型窗口、tokenizer 和预算须另行锁定；本组不会把演示值填成正式材料。

详细参数、SDK token-count 预检、一次推理授权、真实用量/缓存词元、超时及未知结果、错误脱敏、保护视图和持久重放，见 [固定版本 SDK 说明](https://github.com/DMoon22222/SRPAgent-Test-Demo01/blob/c5e04a4ab2f9d80b98439e42228cc3515e0b0534/docs/claude_sdk_integration.md)。能力发现不调用 SDK；公开诊断不执行或重跑目标源码。

## 当前证据

- [0.4.0 默认规则能力](contracts/v2/capabilities_v0.4.0.json)、[11 月 4 日静态/规则样例](contracts/v2/examples_v0.4.0.json)及[样例核对](verification/claude_registration_samples_v0.4.0.json)。这些样例的模型、检索和目标执行均为 0。
- [11 月 2 日离线验证](verification/claude_sdk_validation.json)：保留其当时未提交的快照描述、测试日期和 26 份 B 仓库相对路径摘要。
- [11 月 4 日发布绑定](verification/claude_sdk_publication.json)：将上述原始快照绑定到实际推送的 c5e04a4；后续文档提交可推进 B 分支。
- [0.3.1 历史交付](p2_handoff_20261030.md)与其真实 Docker/P2 矩阵原样保留，旧样例继续注明原版本。精确源码检查应在相应固定提交执行，不将旧实验改写为 0.4.0 通过。

公开样例用于结构和事实核对；重新调用时须刷新关联标识、期限，并按实际内容重算哈希。

`mixed_validation` 表示已有混合技术证据，具体分版本范围以上表和每份原始摘要为准；它不是 O 签收。B-001 的 done 表示本组候选交付，TEST-001、INTB-001、O-001 和 MILESTONE-001 的正式状态由实际材料决定。

接收时按 [O 核对单](integration/receiver_checklist_v0.4.0.md)记录版本、模式、配置及实际意见；截止进展与仍缺材料见 [11 月 5 日准备报告](m1_readiness_20261105.md)。登记、PR 共享和检查通过均不补造接收人、签名或真实模型结果。

## 2026-11-07 三组混合联调补充

以下是晚于上述 11 月 4 日登记的新记录，不回写原候选的历史验收状态。2026-11-07 22:43（Asia/Shanghai），B 组以固定合成加法任务完成了一次 A/B/C 经 O 的混合联调，终态为 `accepted`，`mock=true`。本次路径上未发现需要修改 B 公共接口的阻塞。

| 组成 | 固定源码提交 | 实际运行范围 |
|---|---|---|
| A | `f1b20bd3b47fdab3060d1ab9b84afe1e95da9ecd` | `reliable_a:create_module`；生成与修复仍为 Mock |
| B | `6d99e31b99d50656fffc51a377752f9992b68dec` | `srp_b:create_module`；真实静态检查、Docker 执行和规则诊断 |
| C / O | `0d441d70c4223884aa300e72294a02761886cf36` | `my_c.adapter:create_module` 与原 O；decide/assess 在运行时适配 DeepSeek，retrieve 为 Mock |
| 模型 | `deepseek-flash`，官方 `https://api.deepseek.com` | 非思考模式、JSON 输出；保留 C 的提示、响应解析和契约校验，SDK 不自动重试 |
| 执行镜像 | `sha256:f5845583361a42bef20999c1795e8d5bfb9ada8ac9e1f0552889e48e04840c32` | 既有本地镜像，无构建、拉取或安全策略变更 |

本次 8 项必需业务能力均有调用，11 项交接检查通过；B 实际执行 3 次，依次为公开测试失败、修复后公开测试通过、受保护最终测试通过。诊断复用原始失败事实，未再次执行代码；固定测试及父版本关系经 O 守卫核对。A/C 请求中未出现隐藏测试正文或身份，运行容器已清理。

DeepSeek 实际调用 2 次：decide 为 419 输入 / 53 输出 tokens，assess 为 944 输入 / 178 输出 tokens，共 1,594 tokens；无模块错误或未知用量。模型拒绝了 Mock 证据，O 正确使用 `keep_no_rag` 回退，传给 A 的证据为空。该次记录没有覆盖真实合格证据进入 A 的路径，也不证明 RAG 收益。

本机私有原件位于 `python_service/.interop/abc-integration-deepseek-20261107T144342004180Z/integration.json`，其同目录保留 O 事件、制品与 B 状态。原件包含受保护验收数据，不随 Git 交付。另一次 C 模型 I/O 被替换的离线联调单独保留在 `.interop/abc-integration-offline-20261107T143048834045Z/`，不计为真实模型证据。

### 可复现入口与无密钥配置

使用 [联调入口](../python_service/scripts/run_abc_integration.py) 和 [DeepSeek 混合配置](integration/config.abc-mixed.deepseek.example.json)。历史运行使用临时入口；新增入口保存相同工厂选择、提供方适配方式和交接检查，不据此声称已重新执行上述真实模型/Docker 运行。

配置中的相对路径以 B 仓库根目录为基准：默认 A/C 位于相邻的 `framework-a`、`framework-c` checkout。接收方先取得对应分支和固定提交；位置不同时修改 `sources.*.path`。入口检查指定版本的运行源码，允许 B 后续仅文档或联调工具的提交；实际 HEAD 和依赖版本仍单独记录。要接入后续真实模块，应另选明确版本和适用配置，不把此 Mock 混合入口作为全真实运行。

Python 需 3.11+，使用同时具备 B 与框架依赖及 `openai` SDK 的环境。本次复用既有 Python 3.12.4 环境，版本为 openai 2.53.0、jsonschema 4.26.0、pydantic 2.13.4，不声称完成干净环境安装。以下命令从 B 仓库根目录执行：

执行模式还需本地已有配置指定的 Docker 镜像；入口不构建或拉取镜像。其他接收环境按 [B 的构建说明](../README.md)准备镜像，并在配置中填写实际 image ID，作为新的环境记录。

```powershell
# 默认只检查路径、固定源码版本与依赖；不取密钥、不调用模型、不启动 Docker。
.\python_service\.venv\Scripts\python.exe -B python_service/scripts/run_abc_integration.py

# 需要重新联调时才使用 --run：会调用收费模型并执行 Docker 测试。
.\python_service\.venv\Scripts\python.exe -B python_service/scripts/run_abc_integration.py --run
```

执行模式优先读取本机进程环境变量 `DEEPSEEK_API_KEY`，未设置时通过隐藏输入读取；不读取 `.env`，不接收命令行密钥，也不将密钥写入配置或结果。DeepSeek 客户端只在进程内替换 C 的模型服务绑定，原 A/B/C 分支代码不因此改写。

每次执行使用独立的 `python_service/.interop/abc-integration/<UTC时间戳>/`，保留版本、无密钥配置、模型请求/响应与真实用量、O 原件及检查结果，不覆盖旧记录。模型调用最多 4 次、修复最多 2 次，保留 O 的调用授权、总预算和 B 沙箱限制；未知结果不自动重试。正常退出码 0 表示本配置的混合接口检查通过，不代表 M1 正式接收。

目前仍缺 A 真实生成/修复、C 真实知识检索和目标 tokenizer、真实合格证据进入 A、规定任务集和其他必要分支，以及生产组/消费组与 O 的正式接收确认。
