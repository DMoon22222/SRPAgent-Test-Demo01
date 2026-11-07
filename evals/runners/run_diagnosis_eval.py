"""Evaluate B rules on fixed public facts, with no execution or model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from time import monotonic

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_response
from reliable_codegen.transport import TransportError
from reliable_codegen.utils import canonical, digest, utcnow
from srp_b import __version__, create_module
from srp_b.module import DIAGNOSE, EXECUTE, STATIC
from srp_b.samples import diagnostic, request
from srp_b.sandbox import log_stream

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals/dataset/diagnosis_cases.jsonl"


class NeverExecute:
    calls = 0

    def execute(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("Feedback-only evaluation must not execute targets")


def load_cases(path=DATASET):
    cases = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    identities = [case["case_id"] for case in cases]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate case_id")
    return cases


def build_request(case, registry):
    """Materialize fresh identities/hashes; preserve the dataset's observed facts."""
    static = case["input_fact"]["kind"] == "static"
    operation = STATIC if static else EXECUTE
    original = request(operation, source=case["source"], task_id=case["case_id"], run_id="eval-" + case["case_id"])
    fact = registry.fixture(operation, kind="response")["payload"]["data"]
    code = original["payload"]["code_artifact"]
    fact.update(
        created_at=utcnow(), task_id=original["task_id"], attempt_id=original["attempt_id"],
        code_artifact_id=code["artifact_id"], revision=code["revision"], code_hash=code["content_hash"],
    )
    fact.update({key: deepcopy(value) for key, value in case["input_fact"].items() if key not in {"kind", "stdout", "stderr"}})
    if static:
        fact["report_id"] = "static-" + case["case_id"]
    else:
        tests = original["payload"]["test_artifact"]
        fact.update(execution_id="execution-" + case["case_id"], test_artifact_id=tests["artifact_id"], test_hash=tests["test_hash"])
        context = fact["execution_context"]
        context.update(
            build_manifest=deepcopy(original["payload"]["build_manifest"]),
            execution_policy=deepcopy(original["payload"]["execution_policy"]),
            actual_runtime=None, package_versions=[], image_digest=None,
            isolation_guarantees={}, measurement_status="unknown",
        )
        context["execution_config_hash"] = digest(canonical({"manifest": context["build_manifest"], "policy": context["execution_policy"]}))
        fact["execution_config_hash"] = context["execution_config_hash"]
        for name in ("stdout", "stderr"):
            fact[name] = log_stream(case["input_fact"][name])
        for test in fact["test_case_results"]:
            test.update(oracle_level="public", expected=None, actual=None)
        fact["tests_total"] = len(fact["test_case_results"]) if fact["test_case_results"] else None
        fact["tests_passed"] = sum(t["status"] == "passed" for t in fact["test_case_results"]) if fact["test_case_results"] else None
    registry.validate("StaticCheckReport" if static else "ExecutionResult", fact)
    return diagnostic(fact, original, static=static)


def resolve_pointer(fact, pointer):
    if not pointer.startswith("/"):
        raise ValueError("Only absolute JSON pointers are accepted")
    current = fact
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not token.isdigit():
                raise ValueError("Invalid array index")
            current = current[int(token)]
        else:
            current = current[token]
    return current


def score_report(case, envelope, report):
    expected = case["expected"]
    source = envelope["payload"]["failure_source"]
    static = source["kind"] == "static"
    fact = source["static_report" if static else "execution_result"]
    identity = fact["report_id" if static else "execution_id"]
    reference_results = []
    texts = []
    for reference in report["evidence_refs"]:
        valid = content_matches = False
        try:
            value = resolve_pointer(fact, reference["pointer"])
            if reference["kind"] == "log_span":
                observed = value["text"]
            else:
                observed = value["message"] or value.get("status", "")
            valid = reference["artifact_id"] == identity and bool(observed.strip())
            content_matches = bool(reference["summary"].strip()) and reference["summary"].strip() in observed
            texts.append(observed)
        except (KeyError, IndexError, TypeError, ValueError):
            pass
        reference_results.append({"pointer": reference["pointer"], "path_and_identity_valid": valid, "summary_matches_observation": content_matches})
    root = report["root_cause"] or ""
    root_words = expected["root_cause_required_any"]
    root_supported = not root_words or any(word.casefold() in root.casefold() for word in root_words)
    observed_text = "\n".join(texts).casefold()
    observed_markers = all(marker.casefold() in observed_text for marker in expected["support_markers"])
    classification = report["failure_class"] == expected["failure_class"]
    path_ok = all(r["path_and_identity_valid"] for r in reference_results)
    content_ok = all(r["summary_matches_observation"] for r in reference_results)
    no_evidence = not expected["evidence_refs"] and expected["failure_class"] == "unknown"
    unsupported_claim = no_evidence and bool(report["hypotheses"] or report["confidence"] is not None)
    checks = {
        "classification": classification,
        "stage": report["failure_stage"] == expected["failure_stage"],
        "next_action": report["next_action"] == expected["next_action"],
        "expected_reference_set": {r["pointer"] for r in report["evidence_refs"]} == set(expected["evidence_refs"]),
        "reference_integrity": path_ok and content_ok,
        "diagnostic_support_rubric": classification and path_ok and content_ok and observed_markers and root_supported,
        "no_unsupported_claim_without_evidence": not unsupported_claim,
    }
    return {
        "case_id": case["case_id"], "checks": checks,
        "passed": all(checks.values()), "references": reference_results,
        "root_cause_determinable": expected["root_cause_determinable"],
        "specific_root_cause_supported": root_supported if expected["root_cause_determinable"] else None,
        "no_evidence_control": no_evidence,
        "observed": {key: report[key] for key in ("failure_class", "failure_stage", "next_action", "root_cause", "confidence")},
    }


def evaluate(dataset=DATASET, *, label="rules"):
    started = monotonic()
    registry = ContractRegistry()
    cases = load_cases(dataset)
    results = []
    canary = NeverExecute()
    with tempfile.TemporaryDirectory(prefix="b-diagnosis-eval-") as temporary:
        module = create_module(state_dir=temporary, diagnosis_backend="rules")
        module.runner = canary
        for case in cases:
            try:
                envelope = build_request(case, registry)
                response = module.call(DIAGNOSE, envelope)
                registry.validate_response(DIAGNOSE, response)
                check_response(envelope, response)
                assert response["payload"]["status"] == "completed", response["payload"]["status"]
                data = response["payload"]["data"]
                assert data["failure_source"] == envelope["payload"]["failure_source"]
                assert response["payload"]["usage"]["execution_calls"] == response["payload"]["usage"]["model_calls"] == 0
                scored = score_report(case, envelope, data["diagnosis_report"])
                scored["checks"]["schema"] = True
            except (AssertionError, KeyError, TypeError, ValueError, OSError, TransportError) as error:
                scored = {"case_id": case["case_id"], "passed": False, "checks": {"schema": False}, "references": [], "error": f"{type(error).__name__}: {error}"}
            results.append(scored)
    references = [reference for result in results for reference in result["references"]]
    def metric(check):
        correct = sum(result["checks"].get(check, False) for result in results)
        return {"correct": correct, "total": len(cases), "rate": correct / len(cases) if cases else None}
    matrix = {}
    for case, result in zip(cases, results, strict=True):
        actual = result.get("observed", {}).get("failure_class", "ERROR")
        row = matrix.setdefault(case["expected"]["failure_class"], {})
        row[actual] = row.get(actual, 0) + 1
    source_paths = ["python_service/srp_b/diagnosis.py", "python_service/app/analyzer/error_signal_extractor.py", "evals/runners/run_diagnosis_eval.py"]
    return {
        "record_version": "1.0", "verified_at": utcnow(), "label": label,
        "implementation_version": __version__,
        "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_hashes": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in source_paths},
        "dataset_sha256": hashlib.sha256(Path(dataset).read_bytes()).hexdigest(),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "scope": "Small curated synthetic fact benchmark; real B rules and schema; no target execution, no A/C/O, no general accuracy claim",
        "support_rubric": "Predeclared observation markers plus conclusion-specific lexical cues; limited deterministic rubric, not an independent human semantic audit",
        "mock_input_facts": True, "mock_diagnosis_backend": False,
        "real_docker": False, "real_claude_api": False, "runner_invocations": canary.calls,
        "metrics": {check: metric(check) for check in ("classification", "stage", "next_action", "diagnostic_support_rubric", "schema")},
        "reference_metrics": {
            "emitted": len(references),
            "valid_paths_and_identities": sum(r["path_and_identity_valid"] for r in references),
            "matching_observation_summaries": sum(r["summary_matches_observation"] for r in references),
        },
        "no_evidence_controls": {
            "total": sum(r.get("no_evidence_control", False) for r in results),
            "unsupported_specific_claims": sum(not r["checks"].get("no_unsupported_claim_without_evidence", True) for r in results),
        },
        "counts": {"total": len(cases), "passed": sum(r["passed"] for r in results), "failed": sum(not r["passed"] for r in results), "skipped": 0},
        "confusion_matrix": matrix, "cases": results,
        "duration_seconds": round(monotonic() - started, 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--output", type=Path, default=ROOT / "evals/reports/diagnosis_eval.json")
    parser.add_argument("--label", default="rules")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; select a fresh path to retain prior evidence")
    result = evaluate(args.dataset, label=args.label)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": result["counts"], "metrics": result["metrics"], "references": result["reference_metrics"]}, indent=2))
    return int(result["counts"]["failed"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
