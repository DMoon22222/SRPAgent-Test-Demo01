from __future__ import annotations

from app.analyzer.enums import (
    ALLOWED_ERROR_SUBTYPES,
    ALLOWED_ERROR_TYPES,
    ALLOWED_FAILED_STAGES,
    normalize_error_subtype,
    normalize_error_type,
    normalize_enum_value,
    normalize_failed_stage,
)

SURFACE_KEYWORDS = ["规则判断", "检测到", "AssertionError", "测试断言失败", "测试失败"]
DEEP_KEYWORDS = ["因为", "导致", "条件", "边界", "返回", "算法", "逻辑", "abs", "排序", "索引", "循环", "变量", "distance", "absolute", "balance", "mean"]
ACTION_WORDS = ["改为", "替换", "增加", "检查", "使用", "调用", "边界", "条件", "遍历", "计算", "返回"]
ACTION_CODE_WORDS = ["abs", "return", "if", "for", "len", "index", "sort", "int", "round", "sum"]
GROUNDED_KEYWORDS = ["SyntaxError", "ZeroDivisionError", "AssertionError", "ModuleNotFoundError", "Timeout", "timeout", "stderr", "errorLog", "ruleDecision", "line", "Main.py", "Traceback"]


def calc_metrics(records: list[dict], group_name: str) -> dict:
    total = len(records)
    empty = {
        "group": group_name,
        "total": total,
        "json_valid_count": 0,
        "json_valid_rate": 0.0,
        "errorType_correct": 0,
        "errorType_accuracy": 0.0,
        "failedStage_correct": 0,
        "failedStage_accuracy": 0.0,
        "errorSubtype_correct": 0,
        "errorSubtype_accuracy": 0.0,
        "needRetrieval_correct": 0,
        "needRetrieval_accuracy": 0.0,
        "semantic_errorType_correct": 0,
        "semantic_errorType_accuracy": 0.0,
        "semantic_failedStage_correct": 0,
        "semantic_failedStage_accuracy": 0.0,
        "semantic_errorSubtype_correct": 0,
        "semantic_errorSubtype_accuracy": 0.0,
        "invalidEnumRate": 0.0,
        "ruleDecisionPreservationRate": 0.0,
        "evidenceNonEmptyRate": 0.0,
        "repairSuggestionNonEmptyRate": 0.0,
        "rootCauseNonEmptyRate": 0.0,
        "rootCauseKeywordHitRate": 0.0,
        "repairKeywordHitRate": 0.0,
        "logicBugExplainRate": 0.0,
        "actionableRepairRate": 0.0,
        "evidenceGroundedRate": 0.0,
        "deepExplanationRate": 0.0,
        "surface_explanation_count": 0,
        "deep_explanation_count": 0,
        "evidence_non_empty_rate": 0.0,
        "repairSuggestion_non_empty_rate": 0.0,
    }
    if total == 0:
        return empty

    counts = {key: 0 for key in empty if key.endswith("_correct")}
    json_valid_count = 0
    invalid_enum = 0
    evidence_non_empty = 0
    repair_non_empty = 0
    root_non_empty = 0
    root_keyword_total = 0
    root_keyword_hits = 0
    repair_keyword_total = 0
    repair_keyword_hits = 0
    logic_bug_total = 0
    logic_bug_explained = 0
    actionable_repair = 0
    grounded_evidence = 0
    deep_explanation = 0
    surface_explanation = 0
    preserved = 0
    preservation_total = 0

    for record in records:
        result = record.get(group_name) or {}
        if _is_json_valid(result):
            json_valid_count += 1

        if _strict(result.get("errorType")) == _strict(record.get("expected_errorType")):
            counts["errorType_correct"] += 1
        if _strict(result.get("failedStage")) == _strict(record.get("expected_failedStage")):
            counts["failedStage_correct"] += 1
        if _strict(result.get("errorSubtype")) == _strict(record.get("expected_errorSubtype")):
            counts["errorSubtype_correct"] += 1
        if bool(result.get("needRetrieval", False)) == bool(record.get("expected_needRetrieval", False)):
            counts["needRetrieval_correct"] += 1

        if _mapped_error_type(result.get("errorType")) == _strict(record.get("expected_errorType")):
            counts["semantic_errorType_correct"] += 1
        if _mapped_stage(result.get("failedStage")) == _strict(record.get("expected_failedStage")):
            counts["semantic_failedStage_correct"] += 1
        if _mapped_subtype(result.get("errorSubtype")) == _strict(record.get("expected_errorSubtype")):
            counts["semantic_errorSubtype_correct"] += 1

        if _has_invalid_enum(result):
            invalid_enum += 1
        if result.get("evidence"):
            evidence_non_empty += 1
        if str(result.get("repairSuggestion") or "").strip():
            repair_non_empty += 1
        if _root_cause_non_empty(result.get("rootCause")):
            root_non_empty += 1
        root_hit = False
        repair_hit = False
        root_keywords = record.get("expected_root_cause_keywords") or []
        repair_keywords = record.get("expected_repair_keywords") or []
        if root_keywords:
            root_keyword_total += 1
            root_hit = keyword_hit(result.get("rootCause", ""), root_keywords)
            if root_hit:
                root_keyword_hits += 1
        if repair_keywords:
            repair_keyword_total += 1
            repair_hit = keyword_hit(result.get("repairSuggestion", ""), repair_keywords)
            if repair_hit:
                repair_keyword_hits += 1
        if record.get("bug_kind") == "LOGIC_BUG_COMPLEX":
            logic_bug_total += 1
            if root_hit or repair_hit:
                logic_bug_explained += 1
        if is_actionable_repair(result.get("repairSuggestion", "")):
            actionable_repair += 1
        if evidence_is_grounded(result.get("evidence"), record):
            grounded_evidence += 1
        if is_deep_explanation(result.get("rootCause", "")):
            deep_explanation += 1
        if is_surface_explanation(result.get("rootCause", "")):
            surface_explanation += 1

        rule = result.get("ruleDecision")
        if isinstance(rule, dict):
            preservation_total += 1
            if (
                _strict(result.get("failedStage")) == _strict(rule.get("failedStage"))
                and _strict(result.get("errorType")) == _strict(rule.get("errorType"))
                and _strict(result.get("errorSubtype")) == _strict(rule.get("errorSubtype"))
                and bool(result.get("needRetrieval", False)) == bool(rule.get("needRetrieval", False))
            ):
                preserved += 1

    metrics = {
        **empty,
        **counts,
        "json_valid_count": json_valid_count,
        "json_valid_rate": json_valid_count / total,
        "errorType_accuracy": counts["errorType_correct"] / total,
        "failedStage_accuracy": counts["failedStage_correct"] / total,
        "errorSubtype_accuracy": counts["errorSubtype_correct"] / total,
        "needRetrieval_accuracy": counts["needRetrieval_correct"] / total,
        "semantic_errorType_accuracy": counts["semantic_errorType_correct"] / total,
        "semantic_failedStage_accuracy": counts["semantic_failedStage_correct"] / total,
        "semantic_errorSubtype_accuracy": counts["semantic_errorSubtype_correct"] / total,
        "invalidEnumRate": invalid_enum / total,
        "ruleDecisionPreservationRate": preserved / preservation_total if preservation_total else 0.0,
        "evidenceNonEmptyRate": evidence_non_empty / total,
        "repairSuggestionNonEmptyRate": repair_non_empty / total,
        "rootCauseNonEmptyRate": root_non_empty / total,
        "rootCauseKeywordHitRate": root_keyword_hits / root_keyword_total if root_keyword_total else 0.0,
        "repairKeywordHitRate": repair_keyword_hits / repair_keyword_total if repair_keyword_total else 0.0,
        "logicBugExplainRate": logic_bug_explained / logic_bug_total if logic_bug_total else 0.0,
        "actionableRepairRate": actionable_repair / total,
        "evidenceGroundedRate": grounded_evidence / total,
        "deepExplanationRate": deep_explanation / total,
        "surface_explanation_count": surface_explanation,
        "deep_explanation_count": deep_explanation,
        "evidence_non_empty_rate": evidence_non_empty / total,
        "repairSuggestion_non_empty_rate": repair_non_empty / total,
    }
    return metrics


def keyword_hit(text: str, keywords: list[str]) -> bool:
    text_lower = (text or "").lower()
    return any(str(keyword).lower() in text_lower for keyword in keywords)


def is_actionable_repair(text: str) -> bool:
    value = text or ""
    lowered = value.lower()
    return (
        any(word in value for word in ACTION_WORDS)
        or any(word in lowered for word in ACTION_CODE_WORDS)
        or len(value.strip()) >= 20
    )


def evidence_is_grounded(evidence, record: dict) -> bool:
    if not evidence:
        return False
    evidence_items = [str(item) for item in evidence if str(item).strip()]
    if not evidence_items:
        return False
    haystacks = [
        record.get("execution_errorLog", ""),
        record.get("code", ""),
        jsonish(record.get("full_agent", {})),
        jsonish(record.get("rule_only", {})),
    ]
    for item in evidence_items:
        if any(keyword.lower() in item.lower() for keyword in GROUNDED_KEYWORDS):
            return True
        if any(item and item in haystack for haystack in haystacks):
            return True
    return False


def is_surface_explanation(text: str) -> bool:
    value = text or ""
    return any(keyword in value for keyword in SURFACE_KEYWORDS) and not is_deep_explanation(value)


def is_deep_explanation(text: str) -> bool:
    value = text or ""
    lowered = value.lower()
    return any(keyword.lower() in lowered for keyword in DEEP_KEYWORDS)


def jsonish(value) -> str:
    return str(value or "")


def _strict(value) -> str:
    return normalize_enum_value(value)


def _mapped_stage(value) -> str:
    return normalize_failed_stage(value)[0]


def _mapped_error_type(value) -> str:
    return normalize_error_type(value)[0]


def _mapped_subtype(value) -> str:
    return normalize_error_subtype(value)[0]


def _has_invalid_enum(result: dict) -> bool:
    return (
        _strict(result.get("failedStage")) not in ALLOWED_FAILED_STAGES
        or _strict(result.get("errorType")) not in ALLOWED_ERROR_TYPES
        or _strict(result.get("errorSubtype")) not in ALLOWED_ERROR_SUBTYPES
    )


def _is_json_valid(result: dict) -> bool:
    if not isinstance(result, dict) or not result:
        return False
    return bool(result.get("json_valid", True))


def _root_cause_non_empty(value) -> bool:
    text = str(value or "").strip()
    return bool(text and text.upper() != "UNKNOWN")
