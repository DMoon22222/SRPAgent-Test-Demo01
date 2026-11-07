# 第一阶段诊断候选集标注规范

适用：[40 条候选](diagnosis_candidates_phase1.jsonl)，不替代原有 [16 条开发回归](diagnosis_cases.jsonl)。候选、标签与评分脚本先于本轮业务源码修改冻结；本说明整理于交付阶段，没有据最终预测回改标签。固定字节 SHA256 为 `37cc2a142dde0287b8d11249f427563e515e2c48cace3a163ee3f9f378be1e93`。

## 标签与依据

每行是一个公开诊断场景。`code_context` 说明源码及完整性；`raw_execution_fact` 是历史事实或合成事实配方，来源见 `source_type/source_ref`。历史行保留原始事实及 `origin_request`；合成配方在评分时通过既有样例工具补齐身份、哈希及合法上下文，不执行其中的代码。

- `expected_failure_class` 使用现有公共枚举。分类与具体根因不同；明确 NameError 可以支持 runtime_error，而不能据此断言变量在哪条控制路径漏赋值。
- `expected_failure_stage` 沿用观察阶段，不因诊断结果重写原始执行阶段。
- `expected_next_action` 是可采取的保守动作。独立异常冲突、只有关键词、截断链或无具体证据通常需要 collect_information；环境问题用 fix_environment；政策拒绝用 stop。完整异常或固定测试断言可进入 repair，仍须保留根因不确定性。
- `expected_evidence_refs` 是相对于同一静态/执行事实的 JSON Pointer 集合。日志指向 `/stdout`、`/stderr`；失败测试指向 `/test_case_results/N`；静态发现指向 `/findings/N`。引用不凭空指向代码行或宿主路径。
- `root_cause_determinable` 表示本场景能否由所给材料确定具体根因，不能仅凭异常名置 true。`expected_root_cause` 允许 null。该标签不是“分类能否确定”。
- `unsupported_root_markers` 仅是少量明确禁止的编造说法，不是完整语义裁判。

## 审核状态

全部 40 行当前为 `pending_review`，`annotation_source` 明示 Codex 初标，`reviewer/reviewed_at` 均为 null。当前人工独立审核数为 **0**。

独立审核人应先读取事实和代码上下文，在看模型/规则预测前独立标注分类、阶段、动作、引用及可确定性，再与初标比较并记录分歧处理。只有实际独立审核后才能将状态设为 `human_reviewed`，填写真实审核人、时间和审核来源；不得将 Codex 自查当作人工审核。新增审核版应使用新数据文件、摘要和报告，保留本次冻结版本。脚本会拒绝缺审核人/时间或仍声称 Codex 来源的 human_reviewed 行；这项元数据检查不能代替验证审核真实发生。

## 评分口径

分类 Accuracy 按样例计数；Precision/Recall/Macro-F1 在真实及预测标签并集上做宏平均，单类分母为零时按 0。混淆矩阵为“预期→预测”。阶段、动作另计正确数/评分样例数。

Evidence P/R 在每个场景的不同引用指针上微平均；指针必须可解析、身份一致、观察非空且摘要确实来自该观察。额外无效引用计 FP；该指标不衡量完整语义蕴含。无证据样例不为证据分母补零或补一。

Unsupported Diagnosis Rate 是有限规则：无效引用、命中禁止说法，或在初标根因不可确定时给出有假设且根因评分 ≥0.75。Unknown/Abstention 是 failure_class=unknown 或 next_action=collect_information 的场景数/评分数。更高拒答率需要结合错误率和业务覆盖判断，不自动等于更好。

`independent_human_reviewed` 与 `provisional_pending_review` 分开输出；前者 n=0 时准确率、P/R/F1 及比率全部 null。调用/Schema 失败另列，必须同时披露总候选数与成功评分数，不能隐去失败改变分母。

此集用于本轮开发及后续人工审核准备，不是盲测、统计校准集或泛化准确率证明。
