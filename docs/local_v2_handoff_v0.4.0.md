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
