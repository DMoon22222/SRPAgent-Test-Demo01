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
        "| 组别 | 输入 | 是否调用 LLM | 目的 |",
        "|---|---|---|---|",
        "| Rule-only | errorLog/stderr | 否 | 测试纯规则基线 |",
        "| LLM raw-log | problem + code + raw errorLog | 是 | 测试无结构化反馈时的模型表现 |",
        "| Full-agent | Execution Feedback + Rule Signals + Prompt | 是 | 测试当前完整 Agent |",
        "",
        "## 4. 汇总指标",
        "",
        "| Group | errorType Acc | failedStage Acc | errorSubtype Acc | needRetrieval Acc | JSON Valid |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for item in metrics:
        lines.append(
            f"| {item['group']} | {_pct(item['errorType_accuracy'])} | {_pct(item['failedStage_accuracy'])} | "
            f"{_pct(item['errorSubtype_accuracy'])} | {_pct(item['needRetrieval_accuracy'])} | {_pct(item['json_valid_rate'])} |"
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
            "- 如果 full-agent 指标最高，说明结构化执行反馈和 Prompt 约束有帮助。",
            "- 如果 rule-only 在简单错误上表现接近 full-agent，说明规则层可以承担基础分类。",
            "- 如果 llm_raw_log 不稳定，说明只把原始日志丢给模型不够可靠。",
            "",
            "## 汇报表述",
            "",
            "本实验在跑通 HumanEval 的基础上，没有直接采用 pass@k 评测代码生成能力，而是选取部分 HumanEval 题目构造 buggy completion，覆盖语法错误、运行时错误、测试断言失败和超时等场景。",
            "",
            "通过 HumanEval 测试机制产生真实执行反馈后，分别使用 rule-only、LLM raw-log 和 full-agent 三种方式进行错误诊断，对比 errorType、failedStage、needRetrieval 等指标。",
            "",
            "实验目的是验证 B 组执行反馈与错误根因分析模块是否能将原始运行日志转化为结构化、可解释、可供后续修复 Agent 使用的诊断结果。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _short_result(result: dict | None) -> str:
    if not result:
        return "UNKNOWN"
    return f"{result.get('errorType', 'UNKNOWN')}/{result.get('failedStage', 'UNKNOWN')}"
