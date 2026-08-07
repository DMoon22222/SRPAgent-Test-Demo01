from __future__ import annotations


def calc_metrics(records: list[dict], group_name: str) -> dict:
    total = len(records)
    if total == 0:
        return {
            "group": group_name,
            "total": 0,
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
            "evidence_non_empty_rate": 0.0,
            "repairSuggestion_non_empty_rate": 0.0,
        }

    json_valid_count = 0
    error_type_correct = 0
    failed_stage_correct = 0
    error_subtype_correct = 0
    need_retrieval_correct = 0
    evidence_non_empty = 0
    repair_non_empty = 0

    for record in records:
        result = record.get(group_name) or {}
        if _is_json_valid(result):
            json_valid_count += 1
        if _norm(result.get("errorType")) == _norm(record.get("expected_errorType")):
            error_type_correct += 1
        if _norm(result.get("failedStage")) == _norm(record.get("expected_failedStage")):
            failed_stage_correct += 1
        if _norm(result.get("errorSubtype")) == _norm(record.get("expected_errorSubtype")):
            error_subtype_correct += 1
        if bool(result.get("needRetrieval", False)) == bool(record.get("expected_needRetrieval", False)):
            need_retrieval_correct += 1
        if result.get("evidence"):
            evidence_non_empty += 1
        if str(result.get("repairSuggestion") or "").strip():
            repair_non_empty += 1

    return {
        "group": group_name,
        "total": total,
        "json_valid_count": json_valid_count,
        "json_valid_rate": json_valid_count / total,
        "errorType_correct": error_type_correct,
        "errorType_accuracy": error_type_correct / total,
        "failedStage_correct": failed_stage_correct,
        "failedStage_accuracy": failed_stage_correct / total,
        "errorSubtype_correct": error_subtype_correct,
        "errorSubtype_accuracy": error_subtype_correct / total,
        "needRetrieval_correct": need_retrieval_correct,
        "needRetrieval_accuracy": need_retrieval_correct / total,
        "evidence_non_empty_rate": evidence_non_empty / total,
        "repairSuggestion_non_empty_rate": repair_non_empty / total,
    }


def _norm(value) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    return text or "UNKNOWN"


def _is_json_valid(result: dict) -> bool:
    if not isinstance(result, dict) or not result:
        return False
    return bool(result.get("json_valid", True))
