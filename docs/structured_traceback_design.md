# B 结构化 Python 错误证据设计

实现位于 [structured_errors.py](../python_service/srp_b/structured_errors.py)。本轮先审查已有 StackFrame、SourceLocation、ExecutionResult、DiagnosisReport，复用 `ExecutionResult.traceback` 与现有 extensions，没有改公共 Schema。

## 三层数据

1. Raw Facts：输入 FailureSource、stderr/stdout、JUnit 测试结果和静态发现。诊断响应原样保留 FailureSource；解析不回写原始日志。Runner 原有输出保留上限继续生效，截断事实保留 truncated=true。
2. Parsed Facts：`extensions.srp_b.structured_errors`，显式 `layer=parsed_facts`。各来源独立解析，保存源 artifact_id/pointer/kind、原始对象摘要、输入/前缀摘要及逐行摘要和日志行号。`representation` 区分原始日志、测试消息、由 error_type+message 组成的解析输入及静态消息；拼接表示不能冒充原始 stderr。
3. Diagnosis Hypotheses：原有 root_cause/hypotheses 与置信度评估。它们是推断，引用派生观察时仍可回溯原始事实；异常类型识别不证明更深的语义根因。

## 解析和投影

支持标准 Python File/line/in、SyntaxError 位置、pytest 短帧和错误摘要、异常类型/消息、NameError 引用符号、多层帧。显式 direct-cause/during-handling 标记连接同组异常，记录关系并以终端异常分类；无因果标记的不同异常保留独立组，供置信度模块处理冲突。`TimeoutExpired` 有显式识别。缩进源码中的异常类标识符不会被当作终端异常。

行号/函数缺失时为 null，无栈为空数组。pytest 短断言位置但无异常类型保留 partial，不杜撰异常类型，也不自动当成被截断的标准 Traceback。标准栈停在帧后则标记 incomplete_stack。`parse_status` success/partial/unavailable 表示解析完整性，不是诊断正确率。

诊断扩展保存完整内部对象；Runner 也在已有 traceback 字段输出去重后的公共 StackFrame（file/line_start/line_end/symbol/message）。这些帧是日志声称的位置，不能证明宿主上存在相应文件。已声明项目相对路径优先匹配；其他宿主绝对路径仅输出 basename，并标记 path_redacted。原始日志按事实原样保留，因而本功能不是原始日志的全量隐私脱敏器。

`validate_parsed` 对同一原始表示重新执行有界解析并作规范化比较；只比 source hash 不能发现被篡改的行号，因此测试也篡改了派生帧。它验证派生一致性，不验证日志生产者真实性。

## 上限和失败隔离

单来源最多 65,536 字符、1,024 行、单行 4,096 字符、64 帧、16 异常；最多 64 来源。超过上限保留部分结果并置截断标志，wire 投影最多 64 帧。正则只在有界行上匹配；来源完整摘要仍线性读取原始文本。输入须经过原有请求/预算/日志大小保护，不把解析上限误认为整个请求的总内存上限。

无法识别时保留原始证据并给 unavailable；执行端可选解析异常只记录解析不可用，不覆盖已有执行状态。格式错乱、缺位置、超长、截断、独立错误、两类链、来源重放及宿主路径测试见 [test_phase1_traceback.py](../python_service/tests/test_phase1_traceback.py)。真实 pytest 失败帧也在本轮 Docker 记录中验证。

本轮没有 Java 原生执行链路，未新增 Java 解析或宣称 Java 实测。ExceptionGroup 树形展开、任意自定义日志格式、依赖版本真因和语义根因仍需后续工作。
