from __future__ import annotations

import json
from typing import Any

from app.analyzer.enums import normalize_error_subtype, normalize_error_type, normalize_failed_stage
from app.analyzer.error_signal_extractor import make_rule_decision, summarize_error_signal
from app.analyzer.prompts import SYSTEM_PROMPT_RULE_FIRST
from app.config import settings
from app.schemas import AnalyzeRequest, ErrorAnalysisResult, RuleDecision


class ErrorAnalyzer:
    def analyze(self, request: AnalyzeRequest) -> ErrorAnalysisResult:
        rule = make_rule_decision(error_log=request.errorLog)
        llm_result: dict[str, Any] = {}

        if settings.dashscope_api_key:
            llm_result = self._call_llm(request, rule)
        else:
            llm_result = {
                "rootCause": "未配置 DASHSCOPE_API_KEY，使用规则层基础诊断。",
                "repairSuggestion": default_repair_suggestion(rule),
                "confidence": rule.confidence,
            }

        return postprocess_analysis(llm_result, rule)

    def _call_llm(self, request: AnalyzeRequest, rule: RuleDecision) -> dict[str, Any]:
        try:
            from openai import OpenAI
        except Exception as exc:
            return {"rootCause": f"openai 包不可用，使用规则层基础诊断：{exc}"}

        user_prompt = self._build_user_prompt(request, rule)
        try:
            client = OpenAI(
                api_key=settings.dashscope_api_key,
                base_url=settings.dashscope_base_url,
            )
            response = client.chat.completions.create(
                model=settings.dashscope_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_RULE_FIRST},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            )
            content = response.choices[0].message.content or ""
            return _parse_json_object(content)
        except Exception as exc:
            return {"rootCause": f"DashScope 调用失败，使用规则层基础诊断：{exc}"}

    def _build_user_prompt(self, request: AnalyzeRequest, rule: RuleDecision) -> str:
        signal_summary = summarize_error_signal(request.errorLog)
        return f"""
【ruleDecision】
{rule.model_dump_json(ensure_ascii=False)}

【题目】
{request.problem}

【语言】
{request.language}

【代码】
{request.code}

【执行反馈】
{request.errorLog}

【规则信号】
{signal_summary}

请只补充解释字段，并仅返回严格 JSON。
""".strip()


def postprocess_analysis(llm_result: dict, rule: RuleDecision) -> ErrorAnalysisResult:
    llm_result = llm_result if isinstance(llm_result, dict) else {}
    normalized = _llm_enum_was_normalized(llm_result)
    rule_stage, _ = normalize_failed_stage(rule.failedStage)
    rule_type, _ = normalize_error_type(rule.errorType)
    rule_subtype, _ = normalize_error_subtype(rule.errorSubtype)

    evidence = merge_evidence(rule.evidence, llm_result.get("evidence"))
    root_cause = str(llm_result.get("rootCause") or rule.explanation or "规则层给出基础诊断。").strip()
    repair = str(llm_result.get("repairSuggestion") or default_repair_suggestion(rule)).strip()
    retrieval_query = rule.retrievalQuery
    if rule.needRetrieval and str(llm_result.get("retrievalQuery") or "").strip():
        retrieval_query = str(llm_result.get("retrievalQuery")).strip()

    return ErrorAnalysisResult(
        failedStage=rule_stage,
        errorType=rule_type,
        errorSubtype=rule_subtype,
        rootCause=root_cause,
        evidence=evidence,
        suspectedLocation=str(llm_result.get("suspectedLocation") or _location_from_evidence(evidence)).strip(),
        needRetrieval=rule.needRetrieval,
        retrievalQuery=retrieval_query,
        repairSuggestion=repair,
        confidence=max(rule.confidence, _safe_float(llm_result.get("confidence", 0.0))),
        ruleDecision=rule,
        classificationSource="RULE_FIRST_LLM_EXPLAIN",
        enumNormalized=normalized,
        llmOverrodeRule=False,
    )


def merge_evidence(rule_evidence: list[str], llm_evidence: Any) -> list[str]:
    merged: list[str] = []
    for item in rule_evidence or []:
        if item and item not in merged:
            merged.append(str(item))
    if isinstance(llm_evidence, list):
        for item in llm_evidence:
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def default_repair_suggestion(rule: RuleDecision) -> str:
    if rule.errorType == "COMPILE_ERROR":
        return "检查语法、缩进、括号、冒号、分号或变量声明。"
    if rule.errorSubtype == "DIVIDE_BY_ZERO":
        return "检查除法表达式中的除数，增加非零判断。"
    if rule.errorSubtype == "INDEX_OUT_OF_BOUNDS":
        return "检查数组、列表或字符串下标边界。"
    if rule.errorType == "WRONG_ANSWER":
        return "根据失败测试检查算法逻辑、边界条件和返回值。"
    if rule.errorType == "TIME_LIMIT_EXCEEDED":
        return "检查循环终止条件和算法复杂度。"
    if rule.errorSubtype == "DEPENDENCY_MISSING":
        return "检查依赖是否安装、模块名是否正确，必要时检索官方文档。"
    return "查看执行反馈和规则证据，定位对应代码并修复后重新运行测试。"


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                return {"rootCause": "模型输出 JSON 解析失败，使用规则层基础诊断。"}
        return {"rootCause": "模型输出不包含 JSON 对象，使用规则层基础诊断。"}


def _llm_enum_was_normalized(llm_result: dict) -> bool:
    changed = False
    if "failedStage" in llm_result:
        _, stage_changed = normalize_failed_stage(llm_result.get("failedStage"))
        changed = changed or stage_changed
    if "errorType" in llm_result:
        _, type_changed = normalize_error_type(llm_result.get("errorType"))
        changed = changed or type_changed
    if "errorSubtype" in llm_result:
        _, subtype_changed = normalize_error_subtype(llm_result.get("errorSubtype"))
        changed = changed or subtype_changed
    return changed


def _safe_float(value: Any) -> float:
    try:
        number = float(value)
    except Exception:
        return 0.0
    return min(1.0, max(0.0, number))


def _location_from_evidence(evidence: list[str]) -> str:
    for item in evidence:
        if ".py:" in item or ".java:" in item:
            return item
    return ""
