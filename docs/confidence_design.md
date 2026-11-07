# B 分类与根因置信度

实现：[confidence.py](../python_service/srp_b/confidence.py)，由 [diagnosis.py](../python_service/srp_b/diagnosis.py) 接入。本轮审查了 RuleDecision、规则提取器、公共 Schema 及所有 confidence 使用处；旧 [error_signal_extractor.py](../python_service/app/analyzer/error_signal_extractor.py) 与旧服务的 RuleDecision float 保持原样。旧 error_analyzer、diagnosis_service、repository/diagnosis 的调用语义不在本轮重构。

## 接口与含义

公开 `DiagnosisReport.confidence` 继续是 number/null，本轮明确对应**根因启发式评分**；hypotheses 中的 confidence 与之保持一致。新增的 `extensions.srp_b.confidence_assessment` 版本为 b-confidence-v1，分别给 classification 与 root_cause 的 score/level/reasons，保存 conflicts、parsed_matches_raw 和原始引用摘要。分数不是统计校准概率，也不表示“有 90% 根因正确”。

HIGH ≥0.8，MEDIUM ≥0.5，LOW 为其余非空分数，UNKNOWN 为 null。分类与根因允许一高一低，消费方不应再以旧 float 的固定值/阈值推定分类确定性。形状、operation、工厂调用和旧业务入口保持兼容，数值含义的收敛属于明确的行为变化。

## 主要规则

| 观察 | 分类评分 | 根因评分/动作 |
|---|---|---|
| 完整、明确异常及位置 | 通常 0.90 | 通常 0.65；异常机制仍是待核实解释 |
| 明确异常但没有位置 | 通常 0.90 | 0.35，不猜行号 |
| 只有异常关键词 | 0.45 | null，收集信息 |
| 有显式异常链 | 采用终端异常 | 根因最高 0.50，保留链关系 |
| 独立终端异常冲突/派生与原始不一致 | 无可靠分类时 null/unknown | null，收集信息 |
| timeout/OOM/infrastructure/policy 原始状态 | 状态分类通常 0.95；policy 未知 | 不让旧代码异常覆盖状态；日志冲突或无根因证据时 null |
| 原始测试失败但无具体异常 | test_failure 通常 0.80 | 仅保留断言检查建议，不声称算法根因已确定 |
| 截断/标准栈缺终端 | 通常最高 0.55 | null，收集信息 |
| 测试文件独立非断言错误 | 保留异常分类，domain=test | 优先检查测试/fixture，收集信息，移除实现修复建议 |
| completed 且 tests passed | none，通常 0.95 | 清除根因和旧日志假设，动作 none |

状态与 passed 结果冲突时不以“通过”覆盖基础设施失败。匹配不到具体异常、只有 FAILED/退出事实不能推断算法错误。无 evidence_refs 时不能输出高置信度根因。静态检查沿用显式 finding，位置/解析不完整时根因评分保守降低。

环境仍进入 fix_environment，政策拒绝仍 stop。明确 TimeoutExpired 保留原 repair 动作，但不把超时归因某个循环或算法；无日志超时则收集更多信息。未知时清理不可靠检索查询，非 repair 时清理实现修复建议。failure_signature 按最终分类与原始 subtype 重新计算，避免保留旧分类的签名。

Claude 可选后端仍只解释有依据的现有假设；模型补充解释后的 root score 为 null/UNKNOWN，原因标为未统计校准，分类评估保留。原 44 项 SDK 离线测试使用真实 SDK + 内存 HTTP MockTransport；本轮真实 Claude API 调用为 0。

测试见 [test_phase1_confidence.py](../python_service/tests/test_phase1_confidence.py)。候选集分数仅反映初标一致性，尚无独立人工标签或概率校准实验；conflict 策略可能增加信息收集次数，自定义异常、嵌套 ExceptionGroup 和混合多故障需要进一步审核。
