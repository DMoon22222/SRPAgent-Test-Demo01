# B组错误分类与根因分析标准

本文档用于说明执行反馈与错误根因分析模块的初版分类标准。模块目标不是自动生成或修复代码，而是把沙箱执行结果转化为可被后续模块消费的结构化诊断结果。

## 输入信号

分析 Agent 主要接收以下信息：

- 题目或需求描述
- 编程语言
- 待分析代码
- 标准化执行反馈：`status`、`failedStage`、`stdout`、`stderr`、`exitCode`、`timeout`、`expectedOutput`、`actualOutput`
- 内置规则提取的日志信号：常见异常名、编译器关键词、疑似文件行号

## 失败阶段 failedStage

| 阶段 | 含义 | 例子 |
| --- | --- | --- |
| `PRE_CHECK` | 执行前检查失败 | 空代码、不支持的语言、环境缺失 |
| `COMPILE` | 编译或语法检查失败 | Java `javac` 报错、Python `py_compile` 失败 |
| `RUNTIME` | 运行阶段失败 | 未捕获异常、进程非 0 退出 |
| `TEST` | 程序运行完成但结果不符合预期 | stdout 与 expectedOutput 不一致 |
| `SANDBOX` | 沙箱执行器内部异常 | Docker 调用异常、执行器自身报错 |
| `UNKNOWN` | 日志不足，无法判断 | 无有效日志或信号冲突 |

## 一级错误类型 errorType

| 类型 | 判断依据 | 是否通常需要检索 |
| --- | --- | --- |
| `COMPILE_ERROR` | 编译器或语法检查失败 | 否，除非涉及第三方库或依赖 |
| `RUNTIME_ERROR` | 运行时异常、Traceback、进程非 0 退出 | 通常否 |
| `WRONG_ANSWER` | 正常运行但输出不一致 | 通常否 |
| `TIME_LIMIT_EXCEEDED` | 编译或运行超时 | 通常否 |
| `LOGIC_ERROR` | 算法逻辑、边界条件或输出格式错误 | 通常否 |
| `API_MISUSE` | API 参数、调用方式、版本行为不明确 | 是 |
| `KNOWLEDGE_GAP` | 当前日志不足，需要外部文档或库知识 | 是 |
| `ENVIRONMENT_ERROR` | 缺少解释器、Docker、依赖环境 | 视情况而定 |
| `SANDBOX_ERROR` | 执行器或沙箱内部错误 | 否，优先检查系统配置 |
| `UNKNOWN` | 证据不足或无法归类 | 视情况而定 |

## 二级错误类型 errorSubtype

| 类型 | 常见信号 |
| --- | --- |
| `SYNTAX_ERROR` | Java 语法错误、Python `SyntaxError` |
| `MISSING_SYMBOL` | Java `cannot find symbol`、未定义变量/方法/类 |
| `TYPE_MISMATCH` | 类型不兼容、参数类型错误 |
| `INDENTATION_ERROR` | Python `IndentationError` |
| `NULL_POINTER` | Java `NullPointerException` |
| `INDEX_OUT_OF_BOUNDS` | Java/Python 下标越界异常 |
| `DIVIDE_BY_ZERO` | Java `ArithmeticException: / by zero`、Python `ZeroDivisionError` |
| `DEPENDENCY_MISSING` | `ModuleNotFoundError`、`ClassNotFoundException`、`NoClassDefFoundError` |
| `API_SIGNATURE_MISMATCH` | 方法参数数量或签名不匹配 |
| `OUTPUT_FORMAT_ERROR` | 输出多空格、换行、大小写或格式不符合预期 |
| `ALGORITHM_ERROR` | 逻辑错误、边界条件遗漏、算法复杂度不合适 |
| `INFINITE_LOOP` | 超时且代码存在循环或阻塞输入风险 |
| `RESOURCE_LIMIT` | 内存、CPU、进程数等资源限制触发 |
| `SANDBOX_INTERNAL_ERROR` | Docker 或执行器内部异常 |
| `UNKNOWN` | 无法从日志中判断具体子类 |

## 分析 Agent 输出字段

```json
{
  "failedStage": "COMPILE",
  "errorType": "COMPILE_ERROR",
  "errorSubtype": "MISSING_SYMBOL",
  "rootCause": "代码中使用了未声明的变量或方法。",
  "evidence": ["stderr 中出现 cannot find symbol"],
  "suspectedLocation": "Main.java:12",
  "needRetrieval": false,
  "retrievalQuery": "",
  "repairSuggestion": "检查变量或方法名是否拼写错误，并在使用前完成声明。",
  "confidence": 0.86
}
```

## 与其他模块的对接边界

- 对 A 组：本模块接收代码、语言、输入输出要求，不负责生成代码或测试。
- 对 C 组：本模块只输出 `needRetrieval` 和 `retrievalQuery`，不负责真实检索和自动修复。
- 对系统集成：本模块负责提供结构化、可解释、可追踪证据的错误分析结果。
