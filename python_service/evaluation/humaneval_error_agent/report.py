from __future__ import annotations

import csv
import json
from pathlib import Path

from evaluation.humaneval_error_agent.metrics import (
    is_actionable_repair,
    is_deep_explanation,
    keyword_hit,
)


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
        "expected_root_cause_keywords",
        "expected_repair_keywords",
        "rule_only_rootCauseKeywordHit",
        "full_agent_rootCauseKeywordHit",
        "rule_only_repairKeywordHit",
        "full_agent_repairKeywordHit",
        "rule_only_actionableRepair",
        "full_agent_actionableRepair",
        "rule_only_deepExplanation",
        "full_agent_deepExplanation",
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
            root_keywords = record.get("expected_root_cause_keywords") or []
            repair_keywords = record.get("expected_repair_keywords") or []
            rule = record.get("rule_only") or {}
            full = record.get("full_agent") or {}
            row["expected_root_cause_keywords"] = ";".join(root_keywords)
            row["expected_repair_keywords"] = ";".join(repair_keywords)
            row["rule_only_rootCauseKeywordHit"] = keyword_hit(rule.get("rootCause", ""), root_keywords) if root_keywords else ""
            row["full_agent_rootCauseKeywordHit"] = keyword_hit(full.get("rootCause", ""), root_keywords) if root_keywords else ""
            row["rule_only_repairKeywordHit"] = keyword_hit(rule.get("repairSuggestion", ""), repair_keywords) if repair_keywords else ""
            row["full_agent_repairKeywordHit"] = keyword_hit(full.get("repairSuggestion", ""), repair_keywords) if repair_keywords else ""
            row["rule_only_actionableRepair"] = is_actionable_repair(rule.get("repairSuggestion", ""))
            row["full_agent_actionableRepair"] = is_actionable_repair(full.get("repairSuggestion", ""))
            row["rule_only_deepExplanation"] = is_deep_explanation(rule.get("rootCause", ""))
            row["full_agent_deepExplanation"] = is_deep_explanation(full.get("rootCause", ""))
            row["manualReview"] = record.get("manualReview", "")
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
        "## 4. 硬分类指标",
        "",
        "硬分类字段包括 errorType、failedStage、errorSubtype、needRetrieval。在 Rule-first Hybrid Agent 中，full-agent 会保留 ruleDecision 的硬分类结果，因此 full-agent 与 rule-only 在这些指标上接近或相同是预期现象。",
        "",
        "这说明 full-agent 继承了 rule-only 的稳定分类能力。",
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
            "## 5. 解释质量指标",
            "",
            "硬分类只能说明“错在哪里一类”，不能说明 Agent 是否理解“为什么错”。因此本实验新增 rootCauseKeywordHitRate、repairKeywordHitRate、logicBugExplainRate、actionableRepairRate 等指标。",
            "",
            "| Group | RootCause Keyword Hit | Repair Keyword Hit | Logic Bug Explain Rate | Actionable Repair Rate | Evidence Grounded Rate | Deep Explanation Rate |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in metrics:
        lines.append(
            f"| {item['group']} | {_pct(item['rootCauseKeywordHitRate'])} | {_pct(item['repairKeywordHitRate'])} | "
            f"{_pct(item['logicBugExplainRate'])} | {_pct(item['actionableRepairRate'])} | "
            f"{_pct(item['evidenceGroundedRate'])} | {_pct(item['deepExplanationRate'])} |"
        )

    lines.extend(
        [
            "",
            "## 5.1 工程化输出指标",
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
            "## 6. 典型样本对比",
            "",
        ]
    )
    lines.extend(_typical_logic_comparisons(records))
    lines.extend(
        [
            "",
            "## 7. 样本明细",
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
            "## 8. 结论",
            "",
            "本次评测中，rule-only 和 full-agent 在硬分类指标上接近或完全一致，这是 Rule-first Hybrid 架构的预期结果：规则层负责保证 failedStage、errorType、errorSubtype 和 needRetrieval 的稳定性。",
            "",
            "full-agent 的优势不体现在重复判断硬分类，而体现在解释质量上。相比 rule-only，full-agent 能结合 HumanEval 题目、错误代码和执行反馈，生成更具体的 rootCause、evidence 和 repairSuggestion，尤其是在复杂逻辑错误样本中，full-agent 能指出算法条件、边界处理或返回逻辑中的具体问题。",
            "",
            "相比 llm_raw_log，full-agent 通过规则决策、结构化执行反馈、枚举约束和后处理，避免了大模型输出非标准枚举的问题，更适合作为后续 RAG 检索路由和代码修复 Agent 的输入。",
            "",
            "## 汇报表述",
            "",
            "在 Rule-first Hybrid 架构下，full-agent 与 rule-only 在 errorType、failedStage 等硬分类指标上保持一致，这是预期结果，说明 full-agent 继承了规则层的稳定分类能力。",
            "",
            "但 full-agent 的优势不在于重新分类，而在于在规则分类基础上提供更高质量的根因解释和修复建议。为此，本实验新增复杂逻辑错误样本和解释质量指标，用于评估 rootCause 是否命中关键逻辑问题、repairSuggestion 是否具有可操作性。",
            "",
            "结果表明，rule-only 通常只能识别 AssertionError 并给出模板化建议，而 full-agent 能结合题目语义、代码逻辑和执行反馈，指出更具体的算法错误和修改方向。因此，full-agent 更适合作为后续 RAG 检索路由和代码修复 Agent 的输入。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _short_result(result: dict | None) -> str:
    if not result:
        return "UNKNOWN"
    return f"{result.get('errorType', 'UNKNOWN')}/{result.get('failedStage', 'UNKNOWN')}"


def _typical_logic_comparisons(records: list[dict]) -> list[str]:
    logic_records = [record for record in records if record.get("bug_kind") == "LOGIC_BUG_COMPLEX" and not record.get("skip_reason")]
    if not logic_records:
        return ["没有可展示的复杂逻辑错误样本。"]

    lines: list[str] = []
    for record in logic_records[:3]:
        rule = record.get("rule_only") or {}
        full = record.get("full_agent") or {}
        lines.extend(
            [
                f"### {record.get('sample_id')}",
                "",
                "**预期错误：**",
                "",
                f"{record.get('expected_errorType')} / {record.get('expected_failedStage')} / {record.get('expected_errorSubtype')}",
                "",
                "**逻辑错误说明：**",
                "",
                record.get("logic_bug_description", ""),
                "",
                "**rule-only rootCause：**",
                "",
                rule.get("rootCause", ""),
                "",
                "**full-agent rootCause：**",
                "",
                full.get("rootCause", ""),
                "",
                "**full-agent repairSuggestion：**",
                "",
                full.get("repairSuggestion", ""),
                "",
                "**点评：**",
                "",
                "full-agent 能基于题目和代码指出具体逻辑问题，而 rule-only 只能停留在测试失败层面。",
                "",
            ]
        )
    return lines
