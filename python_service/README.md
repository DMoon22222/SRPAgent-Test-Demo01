# SRP B 组 Python FastAPI 服务

这个目录是 B 组执行反馈与错误根因分析模块的 Python 版实现。它保留 Java 版的主要 HTTP 语义，新增 FastAPI 服务、local/docker 执行模式、DashScope 根因分析、HumanEval 风格批量用例执行，以及 SWE-agent 风格的 `AgentObservation`。

## 安装

Windows：

```bash
cd python_service
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Linux/macOS：

```bash
cd python_service
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 配置阿里云 Key

打开 `.env`，填写 `DASHSCOPE_API_KEY`。不要把真实 Key 提交到仓库。

本服务也兼容已有的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL_ID` 命名；如果同时配置 `DASHSCOPE_*` 与 `LLM_*`，优先使用 `DASHSCOPE_*`。`DASHSCOPE_BASE_URL` 和 `DASHSCOPE_MODEL` 根据阿里云百炼控制台实际开通情况调整。

## 构建 Docker 沙箱镜像

在 Java 项目根目录执行：

```bash
docker build -t srp-code-sandbox:latest -f docker/sandbox/Dockerfile docker/sandbox
```

测试：

```bash
docker run --rm srp-code-sandbox:latest
```

应看到 Java 和 Python 版本信息。

## 启动服务

```bash
cd python_service
uvicorn app.main:app --reload --port 8080
```

## Apifox / curl 测试样例

ping：

```bash
curl http://localhost:8080/api/ping
```

Python 成功：

```bash
curl -X POST http://localhost:8080/api/execute-and-analyze ^
  -H "Content-Type: application/json" ^
  -d "{\"problem\":\"输出 2 和 3 的和\",\"language\":\"python\",\"code\":\"a = 2\nb = 3\nprint(a + b)\",\"stdin\":\"\",\"expectedOutput\":\"5\"}"
```

Python 语法错误：

```json
{
  "problem": "测试 Python 语法错误",
  "language": "python",
  "code": "print('Hello'",
  "stdin": "",
  "expectedOutput": "Hello"
}
```

预期：

```text
status = COMPILE_ERROR
failedStage = COMPILE
```

Python 运行错误：

```json
{
  "problem": "测试 Python 运行时错误",
  "language": "python",
  "code": "a = 10 / 0\nprint(a)",
  "stdin": "",
  "expectedOutput": ""
}
```

预期：

```text
status = RUNTIME_ERROR
failedStage = RUNTIME
```

Docker `/workspace` 验证：

```json
{
  "problem": "测试当前代码是否运行在 Docker 容器中",
  "language": "python",
  "code": "import os\nprint(os.getcwd())",
  "stdin": "",
  "expectedOutput": "/workspace"
}
```

如果 `SANDBOX_MODE=docker`，预期：

```text
actualOutput = /workspace
```

批量测试：

```json
{
  "problem": "读取两个整数输出和",
  "language": "python",
  "code": "a,b=map(int,input().split())\nprint(a+b)",
  "testCases": [
    {"caseId": "case-1", "stdin": "1 2", "expectedOutput": "3"},
    {"caseId": "case-2", "stdin": "10 20", "expectedOutput": "30"},
    {"caseId": "case-3", "stdin": "-1 1", "expectedOutput": "0"}
  ]
}
```

预期：

```text
summary.total = 3
summary.passed = 3
summary.passRate = 1.0
```

## API 列表

- `GET /api/ping`
- `POST /api/analyze-error`
- `POST /api/execute-and-analyze`
- `POST /api/check-syntax`
- `POST /api/execute-batch`

## 测试

```bash
cd python_service
pytest
```

## 设计来源与后续扩展

1. HumanEval 启发：
   HumanEval 的核心流程是 completion -> test execution -> passed / failed / timed out。因此本服务新增 `/api/execute-batch`，用于支持多测试用例执行和 `passRate` 统计。

2. SWE-agent 启发：
   SWE-agent 强调 Agent-Computer Interface，即 Agent 需要结构化、简洁、可执行的环境反馈。因此本服务在 `Execution` 中新增 `AgentObservation`，包含 `stage`、`status`、`importantSignals`、`shortSummary` 和 `nextActionHint`。

3. SWE-bench 后续扩展：
   当前服务是代码片段级执行。后续可以扩展为 patch 级仓库执行：`repo + baseCommit + modelPatch + FAIL_TO_PASS + PASS_TO_PASS`。
