from __future__ import annotations

import sys
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from evaluation.humaneval_error_agent.baselines import analyze_llm_raw_log, analyze_rule_only
from evaluation.humaneval_error_agent.buggy_samples import DEFAULT_TASK_IDS, build_buggy_samples
from evaluation.humaneval_error_agent.config import config
from evaluation.humaneval_error_agent.humaneval_adapter import build_full_code, load_humaneval_problems
from evaluation.humaneval_error_agent.metrics import calc_metrics
from evaluation.humaneval_error_agent.report import write_reports

GROUPS = ["rule_only", "llm_raw_log", "full_agent"]


def main() -> None:
    try:
        problems = load_humaneval_problems()
    except Exception as exc:
        print(f"Failed to load HumanEval problems: {exc}")
        raise

    print(f"Loaded HumanEval problems: {len(problems)}")
    task_ids = [task_id for task_id in DEFAULT_TASK_IDS if task_id in problems][: config.max_tasks]
    samples = build_buggy_samples(task_ids)
    print(f"Built buggy samples: {len(samples)}")

    records: list[dict] = []
    for sample in samples:
        print(f"Running sample {sample['sample_id']} ...")
        records.append(run_sample(sample, problems))

    metric_rows = [calc_metrics(records, group) for group in GROUPS]
    paths = write_reports(records, metric_rows, config.result_dir)

    print("\n=== Summary ===")
    for metric in metric_rows:
        print(f"Group: {metric['group']}")
        print(f"errorType_accuracy: {metric['errorType_accuracy']:.2f}")
        print(f"failedStage_accuracy: {metric['failedStage_accuracy']:.2f}")
        print(f"needRetrieval_accuracy: {metric['needRetrieval_accuracy']:.2f}")
        print()
    print("Results saved to:")
    for path in paths.values():
        print(path)


def run_sample(sample: dict, problems: dict) -> dict:
    base_record = _base_record(sample)
    problem = problems.get(sample["task_id"])
    if not problem:
        base_record["skip_reason"] = f"Task not found: {sample['task_id']}"
        return _fill_skipped_groups(base_record)

    full_code = build_full_code(
        prompt=problem["prompt"],
        completion=sample["completion"],
        test=problem["test"],
        entry_point=problem["entry_point"],
        pass_marker=config.pass_marker,
    )

    skip_reason = _skip_reason_for_incompatible_completion(full_code, sample)
    if skip_reason:
        base_record["skip_reason"] = skip_reason
        return _fill_skipped_groups(base_record)

    payload = {
        "problem": problem["prompt"],
        "language": "python",
        "code": full_code,
        "stdin": "",
        "expectedOutput": config.pass_marker,
        "benchmark": "humaneval",
    }

    try:
        body = _post_json(
            config.execute_and_analyze_url,
            payload,
        )
    except Exception as exc:
        base_record["request_error"] = str(exc)
        return _fill_skipped_groups(base_record)

    execution = normalize_humaneval_execution(body.get("execution") or {})
    full_agent = body.get("analysis")
    if not full_agent:
        full_agent = _fallback_analyze_error(problem["prompt"], full_code, execution)

    raw_error_log = execution.get("errorLog") or execution.get("stderr") or ""
    base_record.update(
        {
            "execution_status": execution.get("status", ""),
            "execution_failedStage": execution.get("failedStage", ""),
            "execution_timeout": execution.get("timeout", False),
            "execution_errorLog": raw_error_log,
            "rule_only": analyze_rule_only(execution),
            "llm_raw_log": analyze_llm_raw_log(problem["prompt"], full_code, raw_error_log),
            "full_agent": _normalize_agent_result(full_agent),
        }
    )
    return base_record


def normalize_humaneval_execution(execution: dict) -> dict:
    normalized = dict(execution or {})
    combined = "\n".join(
        str(normalized.get(key) or "")
        for key in ("errorLog", "stderr", "stdout", "status", "failedStage")
    )
    if "AssertionError" in combined:
        normalized["status"] = "WRONG_ANSWER"
        normalized["failedStage"] = "TEST"
        normalized["compileSuccess"] = True
    return normalized


def _fallback_analyze_error(problem: str, code: str, execution: dict) -> dict:
    payload = {
        "problem": problem,
        "language": "python",
        "code": code,
        "errorLog": execution.get("errorLog") or execution.get("stderr") or "",
    }
    try:
        return _post_json(config.analyze_error_url, payload)
    except Exception as exc:
        return _unknown_result(f"full-agent fallback analyze-error failed: {exc}")


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.request_timeout_sec) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    return json.loads(text)


def _base_record(sample: dict) -> dict:
    return {
        "sample_id": sample["sample_id"],
        "task_id": sample["task_id"],
        "bug_kind": sample["bug_kind"],
        "expected_errorType": sample["expected_errorType"],
        "expected_failedStage": sample["expected_failedStage"],
        "expected_errorSubtype": sample["expected_errorSubtype"],
        "expected_needRetrieval": sample["expected_needRetrieval"],
        "description": sample.get("description", ""),
        "execution_status": "",
        "execution_failedStage": "",
        "execution_timeout": False,
        "execution_errorLog": "",
        "request_error": "",
        "skip_reason": "",
    }


def _fill_skipped_groups(record: dict) -> dict:
    unknown = _unknown_result(record.get("skip_reason") or record.get("request_error") or "sample skipped")
    record["rule_only"] = unknown
    record["llm_raw_log"] = unknown
    record["full_agent"] = unknown
    return record


def _skip_reason_for_incompatible_completion(full_code: str, sample: dict) -> str:
    if sample["expected_errorType"] == "COMPILE_ERROR":
        return ""
    try:
        compile(full_code, "<humaneval_sample>", "exec")
    except SyntaxError as exc:
        return f"Completion incompatible with task prompt indentation: {exc}"
    return ""


def _normalize_agent_result(result: Any) -> dict:
    if not isinstance(result, dict):
        return _unknown_result("agent result missing or not a JSON object")
    normalized = {
        "failedStage": result.get("failedStage") or "UNKNOWN",
        "errorType": result.get("errorType") or "UNKNOWN",
        "errorSubtype": result.get("errorSubtype") or "UNKNOWN",
        "rootCause": result.get("rootCause") or "",
        "evidence": result.get("evidence") if isinstance(result.get("evidence"), list) else [],
        "suspectedLocation": result.get("suspectedLocation") or "",
        "needRetrieval": bool(result.get("needRetrieval", False)),
        "retrievalQuery": result.get("retrievalQuery") or "",
        "repairSuggestion": result.get("repairSuggestion") or "",
        "confidence": result.get("confidence", 0.0),
        "json_valid": True,
    }
    return normalized


def _unknown_result(reason: str) -> dict:
    return {
        "failedStage": "UNKNOWN",
        "errorType": "UNKNOWN",
        "errorSubtype": "UNKNOWN",
        "rootCause": reason,
        "evidence": [],
        "suspectedLocation": "",
        "needRetrieval": False,
        "retrievalQuery": "",
        "repairSuggestion": "",
        "confidence": 0.0,
        "json_valid": False,
    }


if __name__ == "__main__":
    main()
