"""Phase-1 provisional evaluation, keeping human-reviewed scores separate."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from time import monotonic

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_response
from reliable_codegen.transport import TransportError
from reliable_codegen.utils import canonical, digest, utcnow

from srp_b import __version__, create_module
from srp_b.module import DIAGNOSE
from srp_b.samples import diagnostic

if __package__:
    from .run_diagnosis_eval import NeverExecute, build_request, resolve_pointer
else:
    from run_diagnosis_eval import NeverExecute, build_request, resolve_pointer

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals/dataset/diagnosis_candidates_phase1.jsonl"


def load_candidates(path=DATASET):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if len({row["case_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate candidate identity")
    for row in rows:
        if row["annotation_status"] not in {"human_reviewed", "pending_review"}:
            raise ValueError("Unsupported annotation status")
        if row["annotation_status"] == "human_reviewed" and (
            not row.get("reviewer") or not row.get("reviewed_at")
            or "codex" in row["annotation_source"].lower()
        ):
            raise ValueError("Human review needs independent reviewer/date/source metadata")
    return rows


def candidate_request(case, registry):
    if "origin_request" in case:
        original = deepcopy(case["origin_request"])
        fact = deepcopy(case["raw_execution_fact"])
        value = diagnostic(fact, original, static=case["origin_kind"] == "static")
        value["attempt_id"] = fact["attempt_id"]
    else:
        value = build_request({
            "case_id": case["case_id"], "source": case["code_context"]["source"],
            "input_fact": deepcopy(case["raw_execution_fact"]),
        }, registry)
    source = value["payload"]["failure_source"]
    if source["kind"] == "execution":
        for name, truncated in case.get("log_truncated", {}).items():
            source["execution_result"][name]["truncated"] = truncated
    registry.validate_request(DIAGNOSE, value)
    return value


def classification_metrics(rows):
    n = len(rows)
    if not n:
        return {"n": 0, "accuracy": None, "precision": None, "recall": None,
                "macro_f1": None, "per_class": {}, "confusion_matrix": {}}
    labels = sorted({r["expected_failure_class"] for r in rows} | {r["observed"]["failure_class"] for r in rows})
    details, matrix = {}, {}
    for row in rows:
        bucket = matrix.setdefault(row["expected_failure_class"], {})
        prediction = row["observed"]["failure_class"]
        bucket[prediction] = bucket.get(prediction, 0) + 1
    for label in labels:
        tp = sum(r["expected_failure_class"] == r["observed"]["failure_class"] == label for r in rows)
        fp = sum(r["expected_failure_class"] != label and r["observed"]["failure_class"] == label for r in rows)
        fn = sum(r["expected_failure_class"] == label and r["observed"]["failure_class"] != label for r in rows)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        details[label] = {"tp": tp, "fp": fp, "fn": fn, "support": tp + fn,
                          "precision": precision, "recall": recall,
                          "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}
    return {"n": n, "accuracy": sum(r["expected_failure_class"] == r["observed"]["failure_class"] for r in rows) / n,
            "precision": sum(v["precision"] for v in details.values()) / len(labels),
            "recall": sum(v["recall"] for v in details.values()) / len(labels),
            "macro_f1": sum(v["f1"] for v in details.values()) / len(labels),
            "averaging": "macro over the union of true/predicted labels; per-class zero division is 0",
            "per_class": details, "confusion_matrix": matrix}


def metrics(rows):
    n = len(rows)
    true_positive = sum(row["evidence"]["tp"] for row in rows)
    false_positive = sum(row["evidence"]["fp"] for row in rows)
    false_negative = sum(row["evidence"]["fn"] for row in rows)
    return {
        "classification": classification_metrics(rows),
        "stage_accuracy": sum(r["stage_matches"] for r in rows) / n if n else None,
        "next_action_accuracy": sum(r["action_matches"] for r in rows) / n if n else None,
        "evidence": {"tp": true_positive, "fp": false_positive, "fn": false_negative,
                     "precision": true_positive / (true_positive + false_positive) if true_positive + false_positive else None,
                     "recall": true_positive / (true_positive + false_negative) if true_positive + false_negative else None},
        "unsupported_diagnosis": {"count": sum(r["unsupported"] for r in rows), "n": n,
                                  "rate": sum(r["unsupported"] for r in rows) / n if n else None},
        "unknown_or_abstention": {"count": sum(r["abstained"] for r in rows), "n": n,
                                  "rate": sum(r["abstained"] for r in rows) / n if n else None},
    }


def score(case, envelope, report):
    source = envelope["payload"]["failure_source"]
    fact = source["static_report" if source["kind"] == "static" else "execution_result"]
    identity = fact["report_id" if source["kind"] == "static" else "execution_id"]
    predicted, invalid = set(), []
    for ref in report["evidence_refs"]:
        try:
            value = resolve_pointer(fact, ref["pointer"])
            text = value.get("text", value.get("message", "")) if isinstance(value, dict) else value
            if ref["artifact_id"] != identity or not isinstance(text, str) or not text.strip():
                raise ValueError("Invalid/empty observed evidence")
            if not ref["summary"].strip() or ref["summary"].strip() not in text:
                raise ValueError("Summary does not originate in the referenced fact")
            predicted.add(ref["pointer"])
        except (ValueError, TypeError, KeyError, IndexError):
            invalid.append(ref["pointer"])
    gold = set(case["expected_evidence_refs"])
    root = (report["root_cause"] or "").casefold()
    high_unsupported = bool(report["hypotheses"]) and not case["root_cause_determinable"] and (report["confidence"] or 0) >= 0.75
    prohibited = any(marker.casefold() in root for marker in case.get("unsupported_root_markers", []))
    return {
        "case_id": case["case_id"], "annotation_status": case["annotation_status"],
        "source_type": case["source_type"], "expected_failure_class": case["expected_failure_class"],
        "stage_matches": report["failure_stage"] == case["expected_failure_stage"],
        "action_matches": report["next_action"] == case["expected_next_action"],
        "evidence": {"tp": len(predicted & gold), "fp": len(predicted - gold) + len(invalid),
                     "fn": len(gold - predicted), "invalid": invalid,
                     "expected": sorted(gold), "predicted": sorted(predicted)},
        "unsupported": bool(invalid or high_unsupported or prohibited),
        "unsupported_reasons": {"invalid_evidence": bool(invalid), "uncertain_root_high_score": high_unsupported, "prohibited_claim": prohibited},
        "abstained": report["failure_class"] == "unknown" or report["next_action"] == "collect_information",
        "observed": {key: deepcopy(report[key]) for key in ("failure_class", "failure_stage", "failure_domain", "confidence", "root_cause", "next_action", "evidence_refs", "extensions")},
    }


def evaluate(dataset=DATASET, label="phase1"):
    started = monotonic()
    cases = load_candidates(dataset)
    registry, canary = ContractRegistry(), NeverExecute()
    outcomes, errors = [], []
    with tempfile.TemporaryDirectory(prefix="b-phase1-eval-") as directory:
        module = create_module(state_dir=directory, diagnosis_backend="rules")
        module.runner = canary
        for case in cases:
            try:
                envelope = candidate_request(case, registry)
                original = deepcopy(envelope["payload"]["failure_source"])
                response = module.call(DIAGNOSE, envelope)
                registry.validate_response(DIAGNOSE, response)
                check_response(envelope, response)
                assert response["payload"]["status"] == "completed", response["payload"]["status"]
                assert response["payload"]["data"]["failure_source"] == original
                assert response["payload"]["usage"]["execution_calls"] == response["payload"]["usage"]["model_calls"] == 0
                outcomes.append(score(case, envelope, response["payload"]["data"]["diagnosis_report"]))
            except (AssertionError, KeyError, TypeError, ValueError, OSError, TransportError) as error:
                errors.append({"case_id": case["case_id"], "error": f"{type(error).__name__}: {error}"})
    reviewed = [r for r in outcomes if r["annotation_status"] == "human_reviewed"]
    pending = [r for r in outcomes if r["annotation_status"] == "pending_review"]
    source_files = ["python_service/srp_b/diagnosis.py", "python_service/srp_b/structured_errors.py",
                    "python_service/srp_b/confidence.py", "evals/runners/run_diagnosis_eval_phase1.py"]
    return {
        "record_version": "1.0", "verified_at": utcnow(), "label": label,
        "implementation_version": __version__, "python": platform.python_version(),
        "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_hashes": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source_files if (ROOT / p).is_file()},
        "dataset_sha256": hashlib.sha256(Path(dataset).read_bytes()).hexdigest(),
        "development_dataset_sha256": hashlib.sha256((ROOT / "evals/dataset/diagnosis_cases.jsonl").read_bytes()).hexdigest(),
        "candidates": len(cases), "scored": len(outcomes), "schema_or_invocation_errors": errors,
        "annotation_counts": dict(Counter(c["annotation_status"] for c in cases)),
        "source_counts": dict(Counter(c["source_type"] for c in cases)),
        "independent_human_reviewed": metrics(reviewed),
        "provisional_pending_review": metrics(pending),
        "scoring_limitations": "Provisional labels are Codex-generated. Unsupported flags are a bounded evidence/high-confidence/prohibited-claim rubric, not independent semantic adjudication. Historical observations are development data, not unseen generalization evidence.",
        "definitions": {"precision_recall": "Macro single-label classification; evidence is micro over distinct source pointers per case",
                        "abstention": "failure_class unknown OR next_action collect_information",
                        "unsupported": "Invalid reference, explicit prohibited claim, or >=0.75 root score on a provisionally nondeterminable root",
                        "zero_human_denominator": "n=0 produces null scores, never a 0% or 100% accuracy claim"},
        "cases": outcomes, "cases_sha256": digest(canonical(outcomes)),
        "target_executions": canary.calls, "real_claude_api_calls": 0,
        "duration_seconds": round(monotonic() - started, 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default="phase1")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new filename")
    result = evaluate(args.dataset, args.label)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"candidates": result["candidates"], "scored": result["scored"], "errors": result["schema_or_invocation_errors"],
                      "pending": result["provisional_pending_review"], "human": result["independent_human_reviewed"]["classification"]}, indent=2))
    return int(bool(result["schema_or_invocation_errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
