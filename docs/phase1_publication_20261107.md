# B 第一阶段加固发布说明

2026-11-07，用户在本轮工程交付后明确要求“将相关推送提交”。本次发布目标为 `https://github.com/DMoon22222/SRPAgent-Test-Demo01.git` 的 `b/local-v2-adapter`，基于 `b4a1684fc44a088ca7dab1cf0ff572bad225ca7c`，不合并主分支。

## 验证快照与发布状态

[交付报告](phase1_diagnosis_hardening.md)、[机器汇总](verification/phase1_test_summary.json)及[材料核对](verification/phase1_material_checks.json)中的 HEAD、未提交/未推送标志是本次发布授权之前的验证时状态，原件保留，不回写成当时已经发布。用户的新指令授权本次提交与推送。最终提交号和远端分支是否一致，以本次 Git 推送及后续远端 SHA 核验为准。

本次提交包含原 37 份加固材料，另补本说明、[发布核对记录](verification/phase1_publication_20261107.json)及 `.gitattributes` 的新材料换行规则。原有 `.pico/`、`Test.py`、`docs/b_group_research_and_delivery_plan.md`、`docs/group_meeting_brief_20261010.md` 不纳入。私有 `.interop`、环境、凭据、原始私有请求/响应和 JUnit 不纳入。

`.gitattributes` 的本次增量仅固定新增材料在 Windows checkout 下的字节，未对旧文件执行 renormalize。旧报告记录的是验证时的工作区原始字节；若既有源码按照仓库已有 eol=lf 规则在暂存时转换换行，发布核对会分别记录验证时和 Git blob 的 SHA256，并验证差异仅为 CRLF→LF，不改写原报告或冒充重跑测试。业务源码相对于前一轮完成状态没有逻辑变化，本次没有重复执行模型、Docker 或 pytest。

## 已有验证和限制

- 最终完整 pytest 为 384 通过、7 个已在修改前 HEAD 复现的历史 P2 版本检查失败、3 跳过；其中定向 155 项全部通过。
- 原 16 条开发回归通过；40 条候选全部为 pending_review，人工独立审核数 0，人工指标为 null。
- 最终真实 Docker 为 8/8 检查、7 次目标执行，真实 Claude API 调用为 0。
- Ruff 无新增告警，4 条历史告警保留；Bandit/pip-audit 未安装，未执行。
- 共同规范、公共 Schema、A/C/O 业务代码、运行时依赖锁和 Docker 安全策略没有修改。本次发布不代表正式 P2/M1 接收或真实全链路完成。

评测详情见[前后对照](verification/phase1_diagnosis_benchmark.md)，最终发布前检查见[发布核对记录](verification/phase1_publication_20261107.json)。
