# B 组轻量加固发布绑定

发布日期：2026-11-07，Asia/Shanghai。B 组轻量加固和功能定位文档已推送到 GitHub 的 `b/local-v2-adapter` 分支，固定实现/材料提交为 [`42f5e66848e7ed49389f3b19ca0f9fcd568154d8`](https://github.com/DMoon22222/SRPAgent-Test-Demo01/commit/42f5e66848e7ed49389f3b19ca0f9fcd568154d8)。软件候选仍为 0.4.0，公共 schema 2.0 和三项业务操作保持不变。

## 发布内容

本提交包含 21 份文件：B 功能定位文档、NameError/KeyError 规则说明改进、真实 Docker 快速验证驱动与记录、16 条固定诊断样例及前后评测、3 项 Hypothesis 属性测试、定向回归和组会报告，以及相应导航与字节保留规则。逐文件 Git 对象 SHA-256 见[机器发布记录](verification/pre_integration_publication_20261107.json)。

原有 `.pico/`、`Test.py`、研究计划和旧组会文档未加入提交。私有 `.interop/`、环境、SQLite、原始请求响应和密钥未提交。

## 验证记录的时间和状态

[开发报告](pre_integration_hardening_20261107.md)、[组会单页](group_meeting_update_20261107.md)和[验证汇总](verification/pre_integration_hardening_20261107.json)保留验证结束时的 HEAD `f4ed4ca` 及“未提交/未推送”状态。它们是当时的验证快照；当前发布事实以本绑定记录为准。源文件和证据摘要已逐项与固定提交的 Git 对象核对一致，没有改写历史验证字段。

延用的实际验证为：最终定向 pytest 103 项通过，包含 3 项属性测试和最终轮 90 个生成输入；Docker 五类检查通过、最终轮目标执行 4 次；固定事实诊断 16 条通过、引用 22 条有效；Ruff 检查 6 份 Python 文件零诊断。基线的两项说明检查不足仍保留，标签未改。小样本说明检查不能表述为通用诊断准确率 100%。

本次发布只核对文件、链接和 Git 对象，没有重新执行这些测试、调用模型或运行目标代码。记录中的 CRLF JSON 按原字节保存；空白检查识别 CR-at-EOL，不为通过检查而修改证据摘要。

发布不代表 O 独立接收、正式 P2、全真实 P3/M1 或真实 Claude 已通过，也没有执行分支合并。
