# B 0.4.0 候选发布记录

发布日期：2026-11-04，Asia/Shanghai。Claude SDK 实现已推送至 `b/local-v2-adapter`，固定实现提交为 **`c5e04a4ab2f9d80b98439e42228cc3515e0b0534`**。实际发布核对见 [机器记录](verification/claude_sdk_publication.json)，评审入口为 [B 项目 PR #1](https://github.com/DMoon22222/SRPAgent-Test-Demo01/pull/1)。当前为待联合接收的候选，PR 尚未合并。

[11 月 2 日验证记录](verification/claude_sdk_validation.json)保留其当时的 `Uncommitted local` 描述；11 月 4 日逐项核对该记录的 26 份源码，确认其 SHA-256 与已推送实现提交的 Git 对象一致。后续说明文档提交可推进分支；消费者应使用上述固定实现提交。没有把发布日改写为测试执行日。

0.4.0 的验证范围为：132 项 B 测试（含 44 项真实 SDK/内存 HTTP 用例）、99 项共同框架测试、可选依赖安装及 wheel 构建/独立解压加载。既有依赖被复用；真实 Claude 请求、干净依赖环境、新的 Docker 实验和 O 独立签收仍待完成。实际启用需要部署者选择已授权模型、通过本机环境注入密钥，并取得 O 的调用授权。

安装、工厂选项、诊断/预算/重放及保护边界见 [SDK 接入说明](claude_sdk_integration.md)，完整 A/B/C 模板见 [Claude 配置](integration/config.b-local.claude.example.json)。默认规则模式仍可使用，不需要模型凭据。发布过程未调用模型或执行目标代码。

已发布 0.3.1 的接入提交 **`145bc77a271ac2efb22fc7e159090fe605f72602`**、P2 工具 **`b3239cadf26da6360862f84a6da80f10717e8dcc`** 及 [P2 历史交付](p2_handoff_20261030.md)保留。其精确源码检查、镜像和真实 Docker 证据须在相应固定提交复现；不将其标注为本次 0.4.0 的新实验。

共同登记通过 [规范仓库 B 草稿 PR #1](https://github.com/H1Unter3/Collaborative_Reliable_CodeGen_Loop/pull/1)评审。O 仍需确认实际采用的版本和模式，提供 TEST-001 锁定材料、实际目标 A 的上下文/tokenizer、消费方字段意见和独立复现/接收记录。B 发布与本组测试不改变正式 P2/P3/M1 状态，也不代填接收人或签名。
