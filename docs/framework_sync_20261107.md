# 共同框架 B 0.4.0 登记资料同步

同步日期：2026-11-07，Asia/Shanghai。来源为共同框架交付分支 `b/local-v2-handoff` 的固定提交 [`5ecb03c3c6a6ab0878657cd9ba3bd8ee71990014`](https://github.com/H1Unter3/Collaborative_Reliable_CodeGen_Loop/commit/5ecb03c3c6a6ab0878657cd9ba3bd8ee71990014)（2026-11-04）。这是将该提交的 B 组交付材料补回 B 仓库的资料同步。

B 0.4.0 的固定实现仍为 `c5e04a4ab2f9d80b98439e42228cc3515e0b0534`；本次没有变更运行源码、公共协议、授权或历史验证记录，也没有执行模型、沙箱或目标代码。正式 P2、P3、M1 和 O 接收保持各自实际证据边界。

## 本仓库入口

| 材料 | 本地入口 |
|---|---|
| 0.4.0 固定候选交付、安装及验证范围 | [交付说明](local_v2_handoff_v0.4.0.md) |
| O / 消费方版本选择、复现和接收意见 | [接收核对单](integration/receiver_checklist_v0.4.0.md) |
| 截至 11 月 4 日的 M1 准备与缺口 | [原时点缺口报告](m1_readiness_20261105.md) |
| 完整规则配置 | [规则配置](integration/config.b-local.v0.4.0.example.json) |
| 完整 Claude 配置 | [Claude 配置](integration/config.b-local.claude.example.json) |
| 0.4.0 默认规则能力与两个公开注册样例 | [能力](contracts/v2/capabilities_v0.4.0.json)、[样例](contracts/v2/examples_v0.4.0.json) |
| 11 月 4 日注册样例与共同登记检查 | [样例记录](verification/claude_registration_samples_v0.4.0.json)、[检查记录](verification/claude_registration_checks_v0.4.0.json) |
| 已有 11 月 2 日 SDK 离线验证与 11 月 4 日发布绑定 | [离线验证](verification/claude_sdk_validation.json)、[发布绑定](verification/claude_sdk_publication.json) |
| 来源、逐文件处理方式及 SHA-256 | [同步清单](integration/framework_sync_20261107.json) |

## 同步范围和记录解释

源提交的 19 份变更均列入同步清单。B 专属资料中，5 份 JSON 按源 Git 对象字节新增，3 份说明文档补入并适配链接；已有的 2 份 SDK 验证/发布记录字节一致，直接复用。Claude 配置与框架版本的 JSON 语义一致，仅缩进不同，保留 B 原文件及其既有摘要。

共同仓库的 8 份状态、组记录、工作项、服务登记、模块导航和文档检查记录仍由共同仓库维护。清单提供它们在固定提交中的路径、SHA-256 和永久链接，并摘录当时 B 登记和工作项状态；不在 B 仓库建立第二份共同台账。

复制的机器证据保留原日期、原结果和原仓库相对路径。例如注册样例记录中的 `modules/b/examples_v0.4.0.json` 指向框架原文件，在本仓库对应 `docs/contracts/v2/examples_v0.4.0.json`；具体映射见同步清单。复制记录中的 passed 仅表示其原有检查范围，本次同步不算重跑。

0.3.1 的 `capabilities.json`、`local_samples.json`、P1/P2 工具和历史摘要保持原样。新 0.4.0 能力/样例使用独立文件名；SDK 离线验证不能代替真实 API 或新版本 Docker 验收。接收人、日期和意见仍由实际接收方填写。
