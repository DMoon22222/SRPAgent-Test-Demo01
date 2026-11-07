# 小规模 Diagnosis Benchmark：2026-11-07

本次使用 B 0.4.0 当前未提交工作区的真实 Rules Backend，输入为 16 条明确标注来源的公开合成事实。没有启动目标代码、Docker 或真实 Claude 请求。源码、数据摘要及逐例结果见[最终记录](../../evals/reports/diagnosis_eval.json)。

## 评测设计

数据来自既有静态/执行/证据回归样例，以及既有错误提取规则对应的自编 Python 异常变体。每条含 case_id、代码上下文、输入事实、预期分类、阶段、证据路径、根因可确定性和下一动作；不使用隐藏最终测试。

分类标签、说明检查条件在首轮执行前固定，前后三次运行的数据 SHA-256 均为 `bdcb97bc95c775e6561ca9f1e7eb8bb7ac35f1a7b2105c6288a1a24bf72411e2`。首轮发现的两项不足保留在[基线记录](../../evals/reports/diagnosis_eval_baseline.json)，没有修改标签来取得通过。

| 样例 | 预期 failure_class | 预期 failure_stage | 预期 next_action |
|---|---|---|---|
| syntax_missing_colon | syntax_error | static | repair |
| indentation_error | syntax_error | static | repair |
| import_missing_symbol | dependency_error | test | repair |
| module_not_found | dependency_error | test | repair |
| undefined_name | runtime_error | test | repair |
| type_mismatch | runtime_error | test | repair |
| index_out_of_bounds | runtime_error | test | repair |
| division_by_zero | runtime_error | test | repair |
| assertion_failure | test_failure | test | repair |
| missing_mapping_key | runtime_error | test | repair |
| execution_timeout | timeout | run | repair |
| docker_environment_unavailable | environment_error | environment | fix_environment |
| policy_rejected | unknown | environment | stop |
| insufficient_evidence | unknown | test | collect_information |
| assertion_without_exception_token | test_failure | test | repair |
| successful_execution_control | none | none | none |

## 结果与评分口径

| 指标 | 基线 | 最终 |
|---|---:|---:|
| 分类符合预标注 | 16/16 | 16/16 |
| 阶段符合预标注 | 16/16 | 16/16 |
| 下一动作符合预标注 | 16/16 | 16/16 |
| 响应符合公共 Schema | 16/16 | 16/16 |
| 引用路径、事实身份有效 | 22/22 | 22/22 |
| 引用摘要来自实际观察 | 22/22 | 22/22 |
| 诊断说明符合事前设定的事实/具体说明检查标准 | 14/16（87.5%） | 16/16（100%） |
| 无证据控制样例中的特定根因误推断 | 0/1 | 0/1 |

这些分母分别是 16 条诊断样例、22 条实际发出的引用、1 条无证据控制样例，不能相互替代。另有成功执行和缺少异常词的断言控制样例。

引用评分分三层：首先核对地址、事实 ID 和非空内容；其次核对引用摘要是否实际来自该观察；最后依据每条样例事前标注的错误信号和根因说明词检查结论。新增负例测试将真实引用配上虚构的数据库故障解释，仍会判定说明不受支持。

第三层是有限的确定性说明标准，不能完整判断任意自然语言的语义，也不能排除所有虚构解释。因此这里的 100% 只适用于本小样本和该标准，不能写成通用诊断准确率或独立人工语义评审通过率。

## 小幅业务改进

基线中的 NameError 和 KeyError 已有正确类别和有效引用，但根因解释只有“运行时异常”。本次仅在 B 的共享规则提取器补充“未定义名称”和“映射键访问失败”的解释及核对建议，使用“通常”“需核对”等措辞保留假设边界。分类、原始子类型、置信度、下一动作、输入事实和公共字段保持原有逻辑。

改善的是两类异常的解释具体性，分类准确率本来就是 16/16，不能声称分类提升了 12.5 个百分点。解释改进后首次结果另存于[中间记录](../../evals/reports/diagnosis_eval_after_explanations.json)，最终结果记录 Ruff 整理后的文件摘要。

## 复现和限制

运行入口及新输出文件命名要求见 [evals README](../../evals/README.md)。评测使用临时 SQLite 状态，重建动态身份和摘要，并用禁止执行的后端计数器确认目标执行次数为 0。最终运行耗时 2.734 秒。

本集属于工程开发回归材料，规模小、按错误类型挑选、没有随机抽样、没有独立留出集。已使用这些样例改进解释后，不能再将其当成未见测试集。输入事实为合成夹具，实际事实采集准确性由[真实 Docker 快速回归](pre_integration_docker_smoke.json)另行观察。进一步的语义有效率、误诊率、根因定位和置信度校准需事前标注并独立评估。
