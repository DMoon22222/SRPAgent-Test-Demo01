# 第一阶段数据来源

本轮候选共 40 条：4 条历史真实 Docker 观察、1 条历史真实 AST 静态失败、1 条历史环境失败探测、34 条自编合成对抗场景。所有预期标签均为 Codex 初标、待人工审核。历史事实真实不意味着标签经过人工审核，也不意味着错误来自真实业务用户。

| case_id | 来源及限制 |
|---|---|
| historical_success | [上一轮真实 Docker 报告](../../docs/verification/pre_integration_docker_smoke.json) SUCCESS 对应的私有原始请求/响应；自编加法夹具 |
| historical_test_failed | 同一轮 TEST_FAILED，保留 stdout 与逐测试观察；自编错误加法夹具 |
| historical_timeout | 同一轮 TIMEOUT；自编无限循环，原始超时事实保持不变 |
| historical_output_limit | 同一轮 OUTPUT_LIMIT；自编有界沙箱内大量输出，原始保留前缀及截断标志 |
| historical_static_failure | [既有公开导出](../../docs/contracts/v2/local_samples.json) static_failure；既有 AST 检查观察 |
| historical_environment_failure | 同一导出 environment_failure；既有环境不可用探测，非一次成功目标执行 |
| adversarial_*（34 条） | Codex 本轮自编事实配方，`source_type=synthetic_adversarial`；没有为生成候选而执行代码，也不冒充新 Docker 记录 |

历史 Docker 原始文件由旧报告的 `private_records` 关联，本机私有 `.interop` 记录不加入公开仓库；候选内保留对应公开完整事实和原始请求，便于无私有目录时复现诊断。数据构建时未读取隐藏最终测试。历史材料均为先前开发中可见的数据，`seen_in_prior_development=true`；其余场景的 false 仅表示新编场景，不表示对开发者盲测。

对抗场景包含基础异常、多栈层、两个 Python 链标记、多种独立异常、测试/fixture 自身错误、缺包/版本/路径导入、Docker/镜像环境、OOM、无日志超时、超时与旧日志冲突、CPU 节流但测试通过、缺异常终端、缺位置、纯关键词、引用中的异常词、两流冲突、截断、输出断言、失败无异常及成功旧日志。逐条来源和预期见 JSONL。

执行环境是 Python；本轮不声称原生 Local v2 支持 Java，也没有用合成 Java 日志充当真实执行覆盖。共同仓库、A/C/O 业务代码和外部业务样例未纳入本轮运行。

候选字节摘要、来源计数和零目标执行记录在[基线](../reports/diagnosis_eval_baseline_phase1.json)与[最终核验](../reports/diagnosis_eval_final_phase1_verified.json)中一致。旧 16 条维持独立开发回归，不与候选合并计算泛化指标。
