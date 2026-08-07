from __future__ import annotations

import json

from app.analyzer.error_signal_extractor import summarize_error_signal
from app.analyzer.prompts import SYSTEM_PROMPT
from app.config import settings
from app.schemas import AnalyzeRequest, ErrorAnalysisResult


class ErrorAnalyzer:
    def analyze(self, request: AnalyzeRequest) -> ErrorAnalysisResult:
        if not settings.dashscope_api_key:
            return _unknown("未配置 DASHSCOPE_API_KEY，跳过大模型根因分析。")

        try:
            from openai import OpenAI
        except Exception as exc:
            return _unknown(f"openai 包不可用，跳过大模型根因分析：{exc}")

        user_prompt = self._build_user_prompt(request)
        try:
            client = OpenAI(
                api_key=settings.dashscope_api_key,
                base_url=settings.dashscope_base_url,
            )
            response = client.chat.completions.create(
                model=settings.dashscope_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            )
            content = response.choices[0].message.content or ""
            return _parse_analysis(content)
        except Exception as exc:
            return _unknown(f"DashScope 调用失败：{exc}")

    def _build_user_prompt(self, request: AnalyzeRequest) -> str:
        signal_summary = summarize_error_signal(request.errorLog)
        return f"""
【题目 / 任务】
{request.problem}

【语言】
{request.language}

【代码】
{request.code}

【执行错误日志】
{request.errorLog}

{signal_summary}

请仅返回严格 JSON。
""".strip()


def _parse_analysis(content: str) -> ErrorAnalysisResult:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                return _unknown("模型输出解析失败，未能从返回内容中提取合法 JSON。")
        else:
            return _unknown("模型输出解析失败，返回内容不包含 JSON 对象。")

    try:
        return ErrorAnalysisResult(**data)
    except Exception as exc:
        return _unknown(f"模型 JSON 字段校验失败：{exc}")


def _unknown(root_cause: str) -> ErrorAnalysisResult:
    return ErrorAnalysisResult(
        failedStage="UNKNOWN",
        errorType="UNKNOWN",
        errorSubtype="UNKNOWN",
        rootCause=root_cause,
        evidence=[],
        suspectedLocation="",
        needRetrieval=False,
        retrievalQuery="",
        repairSuggestion="请先检查执行反馈；如需大模型分析，请确认 DashScope API Key、base_url 和模型名称配置正确。",
        confidence=0.0,
    )
