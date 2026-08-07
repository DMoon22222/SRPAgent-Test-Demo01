from __future__ import annotations

import csv
import json
from pathlib import Path


RECORDS_JSONL = "humaneval_error_agent_records.jsonl"
RECORDS_CSV = "humaneval_error_agent_records.csv"
SUMMARY_MD = "humaneval_error_agent_summary.md"


def write_reports(records: list[dict], metrics: list[dict], result_dir: Path) -> dict[str, Path]:
    result_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = result_dir / RECORDS_JSONL
    csv_path = result_dir / RECORDS_CSV
    md_path = result_dir / SUMMARY_MD

    _write_jsonl(records, jsonl_path)
    _write_csv(records, csv_path)
    _write_markdown(records, metrics, md_path)
    return {"jsonl": jsonl_path, "csv": csv_path, "markdown": md_path}


def _write_jsonl(records: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_csv(records: list[dict], path: Path) -> None:
    fieldnames = [
        "sample_id",
        "task_id",
        "bug_kind",
        "expected_errorType",
        "expected_failedStage",
        "expected_errorSubtype",
        "expected_needRetrieval",
        "execution_status",
        "execution_failedStage",
        "execution_timeout",
        "rule_only_errorType",
        "llm_raw_log_errorType",
        "full_agent_errorType",
        "rule_only_rootCause",
        "llm_raw_log_rootCause",
        "full_agent_rootCause",
        "rule_only_repairSuggestion",
        "llm_raw_log_repairSuggestion",
        "full_agent_repairSuggestion",
        "manualReview",
        "request_error",
        "skip_reason",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = {key: record.get(key, "") for key in fieldnames}
            row["rule_only_errorType"] = (record.get("rule_only") or {}).get("errorType", "")
            row["llm_raw_log_errorType"] = (record.get("llm_raw_log") or {}).get("errorType", "")
            row["full_agent_errorType"] = (record.get("full_agent") or {}).get("errorType", "")
            row["rule_only_rootCause"] = (record.get("rule_only") or {}).get("rootCause", "")
            row["llm_raw_log_rootCause"] = (record.get("llm_raw_log") or {}).get("rootCause", "")
            row["full_agent_rootCause"] = (record.get("full_agent") or {}).get("rootCause", "")
            row["rule_only_repairSuggestion"] = (record.get("rule_only") or {}).get("repairSuggestion", "")
            row["llm_raw_log_repairSuggestion"] = (record.get("llm_raw_log") or {}).get("repairSuggestion", "")
            row["full_agent_repairSuggestion"] = (record.get("full_agent") or {}).get("repairSuggestion", "")
            row["manualReview"] = ""
            writer.writerow(row)


def _write_markdown(records: list[dict], metrics: list[dict], path: Path) -> None:
    lines = [
        "# HumanEval 错误诊断样本评测报告",
        "",
        "## 1. 实验目的",
        "",
        "HumanEval 原本用于评测代码生成模型的函数补全能力。本实验不使用 pass@k 作为核心指标，也不让 Qwen 生成代码，而是选取 HumanEval 题目和测试用例，人为构造错误 completion，通过真实执行反馈评估 B 组错误分析 Agent 的诊断能力。",
        "",
        "## 2. 实验流程",
        "",
        "HumanEval prompt -> buggy completion -> HumanEval test -> execution feedback -> rule-only / raw-log LLM / full-agent。",
        "",
        "## 3. 对照组设计",
        "",
        "| 组别 | 作用 | 优点 | 局限 |",
        "|---|---|---|---|",
        "| rule-only | 纯规则分类基线 | 稳定、快速、对典型日志准确 | 只能识别表层错误，难以解释复杂逻辑根因 |",
        "| llm_raw_log | 直接把原始日志给 Qwen | 有一定语义理解能力 | 输出不稳定，枚举不统一，难以直接接入后续模块 |",
        "| full-agent | 规则分类 + 结构化执行反馈 + LLM 解释 | 兼具稳定分类和解释能力，可给修复建议和 RAG 查询 | 需要维护规则和 Prompt |",
        "",
        "## 4. 汇总指标",
        "",
        "| Group | exact errorType | semantic errorType | exact failedStage | semantic failedStage | needRetrieval | invalidEnum | JSON Valid |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for item in metrics:
        lines.append(
            f"| {item['group']} | {_pct(item['errorType_accuracy'])} | {_pct(item['semantic_errorType_accuracy'])} | "
            f"{_pct(item['failedStage_accuracy'])} | {_pct(item['semantic_failedStage_accuracy'])} | "
            f"{_pct(item['needRetrieval_accuracy'])} | {_pct(item['invalidEnumRate'])} | {_pct(item['json_valid_rate'])} |"
        )

    lines.extend(
        [
            "",
            "## 4.1 解释能力与工程化指标",
            "",
            "| Group | rootCause NonEmpty | evidence NonEmpty | repairSuggestion NonEmpty | ruleDecision Preservation |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for item in metrics:
        lines.append(
            f"| {item['group']} | {_pct(item['rootCauseNonEmptyRate'])} | {_pct(item['evidenceNonEmptyRate'])} | "
            f"{_pct(item['repairSuggestionNonEmptyRate'])} | {_pct(item['ruleDecisionPreservationRate'])} |"
        )

    lines.extend(
        [
            "",
            "## 5. 样本明细",
            "",
            "| sample_id | expected | rule_only | llm_raw_log | full_agent | 备注 |",
            "|---|---|---|---|---|---|",
        ]
    )

    for record in records:
        expected = f"{record.get('expected_errorType')}/{record.get('expected_failedStage')}"
        lines.append(
            "| {sample_id} | {expected} | {rule} | {raw} | {full} | {note} |".format(
                sample_id=record.get("sample_id", ""),
                expected=expected,
                rule=_short_result(record.get("rule_only")),
                raw=_short_result(record.get("llm_raw_log")),
                full=_short_result(record.get("full_agent")),
                note=record.get("skip_reason") or record.get("request_error") or "",
            )
        )

    lines.extend(
        [
            "",
            "## 6. 初步结论",
            "",
            "本次改进后，full-agent 使用 Rule-first Hybrid 架构，由规则层锁定 failedStage、errorType、errorSubtype、needRetrieval，再由 LLM 生成 rootCause、evidence、repairSuggestion 和 retrievalQuery。",
            "",
            "相比 rule-only，full-agent 不仅能保持基础分类稳定性，还能提供可解释根因和修复建议；相比 llm_raw_log，full-agent 的输出遵循统一枚举和结构化 schema，更适合作为后续 RAG 路由和代码修复 Agent 的输入。",
            "",
            "- 如果 llm_raw_log 的 semantic 指标高于 exact 指标，说明它具备一定语义识别能力，但缺少枚举约束和后处理。",
            "- 如果 full-agent invalidEnumRate 为 0 且 ruleDecisionPreservationRate 接近 100%，说明规则硬分类被稳定保留。",
            "- 对复杂逻辑错误，建议结合 CSV 中 rootCause、repairSuggestion 和 manualReview 做人工复核。",
            "",
            "## 汇报表述",
            "",
            "上一版实验中，rule-only 在基础错误分类上表现较高，而 full-agent 的 failedStage 判断存在 RUNTIME 与 TEST 混淆。因此本次将错误分析 Agent 改造为 Rule-first Hybrid 架构：规则层负责确定 failedStage、errorType、errorSubtype 和 needRetrieval，大模型负责根据结构化执行反馈补充 rootCause、evidence 和 repairSuggestion。",
            "",
            "这种设计保留了 rule-only 的稳定性，同时补充了纯规则难以提供的根因解释和修复建议；相比直接调用大模型分析原始日志，full-agent 的输出遵循统一枚举和 schema，更适合作为后续 RAG 检索路由和代码修复 Agent 的输入。",
            "",
            "最终系统体现为：rule-only 稳定但解释能力弱；llm_raw_log 有语义理解但输出不稳定、枚举不可控；full-agent 由规则层保证分类稳定，由 LLM 负责解释和修复建议，并通过后处理保证输出可工程化对接。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _short_result(result: dict | None) -> str:
    if not result:
        return "UNKNOWN"
    return f"{result.get('errorType', 'UNKNOWN')}/{result.get('failedStage', 'UNKNOWN')}"
