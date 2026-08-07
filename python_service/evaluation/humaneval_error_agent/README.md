# HumanEval 错误诊断样本评测

## 实验目的

本实验基于 HumanEval 构造错误诊断样本，用于评测 B 组错误根因分析 Agent。

HumanEval 原本用于评测代码生成模型的函数补全能力，即 `prompt -> model completion -> tests -> pass@k`。本实验不使用 `pass@k` 作为核心指标，也不让 Qwen 生成代码。本实验选取 HumanEval 题目和测试用例，人为构造错误 completion，通过测试失败日志评估 B 组错误分析 Agent 的诊断能力。

换句话说：

- 原 HumanEval：评测模型能否写出正确代码。
- 本实验：评测错误分析 Agent 能否根据执行反馈诊断错误原因。

## 准备环境

在 `python_service` 目录安装依赖：

```bash
cd python_service
pip install -r requirements.txt
```

如果 HumanEval 没装，也可以使用本地克隆方式：

```bash
git clone https://github.com/openai/human-eval
pip install -e human-eval
```

不建议把 HumanEval 仓库复制进本项目。

## 启动 B 组服务

Python FastAPI 版：

```bash
cd python_service
uvicorn app.main:app --reload --port 8080
```

如果使用项目虚拟环境，也可以：

```bash
cd python_service
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8080
```

如果当前仍使用 Java Spring Boot 版，只要它提供兼容的 `POST /api/execute-and-analyze` 请求/响应字段，也可以直接运行本评测脚本。

## 运行评测

```bash
cd python_service
python -m evaluation.humaneval_error_agent.run_eval
```

或：

```bash
python evaluation/humaneval_error_agent/run_eval.py
```

默认会选取 `HumanEval/0` 到 `HumanEval/4`，每题构造 5 类错误样本，共 25 条：

- COMPILE_ERROR / SYNTAX_ERROR
- RUNTIME_ERROR / DIVIDE_BY_ZERO
- WRONG_ANSWER / ALGORITHM_ERROR
- TIME_LIMIT_EXCEEDED / INFINITE_LOOP
- API_MISUSE / DEPENDENCY_MISSING

## 对照组设计

| 组别 | 输入 | 是否调用 LLM | 目的 |
|---|---|---|---|
| Rule-only | errorLog/stderr | 否 | 测试纯规则基线 |
| LLM raw-log | problem + code + raw errorLog | 是 | 测试无结构化反馈时的模型表现 |
| Full-agent | Execution Feedback + Rule Signals + Prompt | 是 | 测试当前完整 Agent |

如果没有配置 DashScope API Key，`llm_raw_log` 会返回 `UNKNOWN`，不会中断评测。`rule_only` 和服务执行反馈仍可运行。

## 查看结果

结果会输出到：

```text
python_service/evaluation/humaneval_error_agent/results/
  humaneval_error_agent_records.jsonl
  humaneval_error_agent_records.csv
  humaneval_error_agent_summary.md
```

## 汇报表述

本实验在跑通 HumanEval 的基础上，没有直接采用 pass@k 评测代码生成能力，而是选取部分 HumanEval 题目构造 buggy completion，覆盖语法错误、运行时错误、测试断言失败和超时等场景。

通过 HumanEval 测试机制产生真实执行反馈后，分别使用 rule-only、LLM raw-log 和 full-agent 三种方式进行错误诊断，对比 errorType、failedStage、needRetrieval 等指标。

实验目的是验证 B 组执行反馈与错误根因分析模块是否能将原始运行日志转化为结构化、可解释、可供后续修复 Agent 使用的诊断结果。

## 本地 HumanEval 仓库

如果已经把 HumanEval 克隆到本地，例如：

```text
D:\human-eval
```

可以直接运行评测脚本。`humaneval_adapter.py` 会自动检测 `D:\human-eval`，并把它加入 Python 导入路径。

也可以显式设置：

```bat
set HUMANEVAL_REPO_DIR=D:\human-eval
```

或安装为 editable 包：

```bat
.\.venv\Scripts\python.exe -m pip install -e D:\human-eval
```

因此 `requirements.txt` 中不再强制使用 `human-eval @ git+https://github.com/openai/human-eval.git`，避免在 GitHub 网络不可达时安装失败。
