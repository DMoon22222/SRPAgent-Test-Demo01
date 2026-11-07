"""Focused root-cause regressions and evaluator negative controls."""

import sys
from copy import deepcopy
from pathlib import Path

import pytest
from reliable_codegen.contracts import ContractRegistry
from srp_b import create_module
from srp_b.module import DIAGNOSE

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evals.runners.run_diagnosis_eval import (
    build_request,
    load_cases,
    score_report,
)


def diagnose_case(case_id, tmp_path):
    case = next(case for case in load_cases() if case["case_id"] == case_id)
    registry = ContractRegistry()
    envelope = build_request(case, registry)
    response = create_module(state_dir=str(tmp_path / "state")).call(DIAGNOSE, envelope)
    registry.validate_response(DIAGNOSE, response)
    assert response["payload"]["status"] == "completed"
    return case, envelope, response["payload"]["data"]["diagnosis_report"]


@pytest.mark.parametrize("case_id,word,subtype", [
    ("undefined_name", "未定义", "MISSING_SYMBOL"),
    ("missing_mapping_key", "键", "UNKNOWN"),
])
def test_specific_exception_explanation_keeps_existing_classification(tmp_path, case_id, word, subtype):
    case, envelope, report = diagnose_case(case_id, tmp_path)
    assert word in report["root_cause"]
    assert report["failure_class"] == "runtime_error" and report["raw_failure_class"] == subtype
    assert report["failure_source"] == envelope["payload"]["failure_source"]
    assert score_report(case, envelope, report)["passed"]


def test_existing_reference_does_not_prove_invented_cause(tmp_path):
    case, envelope, report = diagnose_case("undefined_name", tmp_path)
    report["root_cause"] = "The remote database is disconnected."
    result = score_report(case, envelope, report)
    assert result["checks"]["reference_integrity"]
    assert not result["checks"]["diagnostic_support_rubric"]


def test_nonexistent_reference_is_rejected_separately(tmp_path):
    case, envelope, report = diagnose_case("undefined_name", tmp_path)
    report = deepcopy(report)
    report["evidence_refs"][0]["pointer"] = "/test_case_results/999"
    result = score_report(case, envelope, report)
    assert not result["checks"]["reference_integrity"]
    assert not result["references"][0]["path_and_identity_valid"]


def test_no_evidence_does_not_become_a_specific_root_cause(tmp_path):
    case, envelope, report = diagnose_case("insufficient_evidence", tmp_path)
    assert not report["hypotheses"] and report["confidence"] is None
    assert report["next_action"] == "collect_information"
    assert score_report(case, envelope, report)["checks"]["no_unsupported_claim_without_evidence"]
