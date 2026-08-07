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
        "evidence_non_empty_rate": evidence_non_empty / total,
        "repairSuggestion_non_empty_rate": repair_non_empty / total,
    }
    return metrics


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
