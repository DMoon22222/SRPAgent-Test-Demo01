# 第一阶段诊断评测对照

候选/标签在改规则前冻结，固定 SHA256 `37cc2a142dde0287b8d11249f427563e515e2c48cace3a163ee3f9f378be1e93`。源码 HEAD 仍为 b4a1684；最终记录通过逐文件摘要绑定未提交实现。评测调用真实 B 规则与公共 Schema，以禁止执行的 canary Runner 核实目标执行为 0，真实模型调用为 0。

## 数据与成绩边界

40 条全部 pending_review：4 历史真实 Docker、1 历史 AST、1 历史环境探测、34 合成对抗。历史错误来自自编开发夹具。人工独立审核 n=0，独立人工 Accuracy/Precision/Recall/Macro-F1 均为 **null**。下面仅是 Codex 初标开发候选的一致性结果，不是独立盲测或真实业务泛化成绩。

| 指标 | 修改前 | 最终 | 分母/定义 |
|---|---:|---:|---|
| 分类 Accuracy | 34/40（85%） | 40/40（100%） | 成功评分候选；两轮调用/Schema 错误均 0 |
| 分类 Precision（macro） | 0.9056 | 1.0000 | 9 类真实/预测标签并集，各类比率再平均 |
| 分类 Recall（macro） | 0.9158 | 1.0000 | 同上 |
| Macro-F1 | 0.8966 | 1.0000 | 各类 F1 平均，非宏 P/R 的调和均值 |
| 阶段一致 | 40/40 | 40/40 | 原事实阶段保持 |
| 下一动作一致 | 29/40 | 40/40 | 与冻结初标一致 |
| Evidence Precision | 39/41（95.12%） | 39/39（100%） | 每例不同引用指针微平均，额外/无效引用计 FP |
| Evidence Recall | 39/39（100%） | 39/39（100%） | 预期引用集合共 39 |
| Unsupported Diagnosis Rate | 27/40（67.5%） | 0/40 | 有限引用/高分/禁止说法规则，非人工语义审查 |
| Unknown/Abstention Rate | 6/40（15%） | 17/40（42.5%） | unknown 分类或 collect_information |

最终混淆矩阵的非零项均在对角：dependency_error 6、environment_error 4、none 3、resource_limit 1、runtime_error 11、syntax_error 2、test_failure 2、timeout 3、unknown 8。完整逐类 TP/FP/FN、矩阵和每例观察保存在 JSON 中。

拒答率上升主要来自纯关键词、冲突、无证据或截断场景的主动信息收集；这不是普遍提高拒答率的优化目标。根因分数上限降低会直接改善本评分规则中的“不可确定根因仍给高分”项，不能将该项的 0/40 描述为零幻觉率。证据指针的正确也不等于根因语义已证实。

## 固定旧开发回归

原 16 条数据、断言及旧报告未改。第一轮本阶段回归为 15/16：TimeoutExpired 不符合单纯 Error/Exception 后缀识别而导致动作/解释变化；修正显式异常识别后最终 **16/16**。分类、阶段、动作、引用和原有说明规则均通过，22 个引用身份/路径/原始摘要均有效。

候选第一轮最终文件为 40/40 分类、39/40 动作。历史 pytest 断言短帧没有异常终端，被错误视为截断标准栈；修正为保留 partial 短帧而不杜撰异常类型后，最终动作 40/40。两个初次结果完整保留，未通过改标签获得提升。

## 记录索引

- [候选数据](../../evals/dataset/diagnosis_candidates_phase1.jsonl)、[标注规范](../../evals/dataset/annotation_guide.md)、[来源说明](../../evals/dataset/data_sources_phase1.md)
- [候选基线](../../evals/reports/diagnosis_eval_baseline_phase1.json)
- [候选首次输出](../../evals/reports/diagnosis_eval_final_phase1.json)，保留已发现的动作问题
- [候选最终核验](../../evals/reports/diagnosis_eval_final_phase1_verified.json)
- [旧 16 条首次回归](../../evals/reports/diagnosis_dev_regression_phase1.json)
- [旧 16 条最终回归](../../evals/reports/diagnosis_dev_regression_phase1_verified.json)

独立复现从仓库根运行（已存在的输出文件会拒绝覆盖）：

```powershell
& '.\python_service\.venv-local-v2\Scripts\python.exe' -X utf8 -B evals/runners/run_diagnosis_eval_phase1.py --output evals/reports/diagnosis_phase1_review_rerun.json --label rerun
& '.\python_service\.venv-local-v2\Scripts\python.exe' -X utf8 -B evals/runners/run_diagnosis_eval.py --output evals/reports/diagnosis_dev_phase1_review_rerun.json --label rerun
```

下一阶段应先取得独立人工审核与新的外部真实公开错误，冻结独立测试集并隔离规则开发，再报告泛化表现或考虑置信度统计校准。本阶段不具备这些证据。
