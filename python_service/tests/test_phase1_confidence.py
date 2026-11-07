"""Evidence strength, authority and parser consistency confidence cases."""

import sys
from copy import deepcopy
from pathlib import Path

from reliable_codegen.contracts import ContractRegistry

from app.analyzer.error_signal_extractor import make_rule_decision
from srp_b.confidence import assess
from srp_b.diagnosis import diagnose
from srp_b.structured_errors import (
    evidence_sources,
    known_workspace_paths,
    parse_sources,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evals.runners.run_diagnosis_eval import build_request

TRACE = 'Traceback (most recent call last):\n  File "src/main.py", line 3, in add\n    return missing\nNameError: name \'missing\' is not defined'


def diagnostic_case(stderr=TRACE, *, stdout="", status="completed", outcome="unknown", stage="run", cases=None):
    fact = {"kind": "execution", "execution_status": status, "test_outcome": outcome,
            "failure_stage": stage, "exit_code": 1, "termination_reason": "normal",
            "stdout": stdout, "stderr": stderr, "test_case_results": cases or []}
    request = build_request({"case_id": "confidence-fixture", "source": "def add(a, b):\n    return a+b\n", "input_fact": fact}, ContractRegistry())
    before = deepcopy(request)
    result = diagnose(request)
    ContractRegistry().validate("DiagnosticResult", result)
    assert request == before and result["failure_source"] == request["payload"]["failure_source"]
    return request, result["diagnosis_report"]


def assessment(report):
    return report["extensions"]["srp_b"]["confidence_assessment"]


def test_explicit_trace_has_high_classification_and_medium_root_score():
    _, report = diagnostic_case()
    detail = assessment(report)
    assert detail["classification"]["level"] == "HIGH"
    assert detail["root_cause"]["level"] == "MEDIUM"
    assert report["confidence"] == detail["root_cause"]["score"] <= 0.65
    assert report["locations"][0]["line_start"] == 3


def test_explicit_exception_without_location_keeps_classification_root_separate():
    _, report = diagnostic_case("NameError: name 'missing' is not defined")
    assert assessment(report)["classification"]["level"] == "HIGH"
    assert assessment(report)["root_cause"]["level"] == "LOW"
    assert not report["locations"]


def test_keyword_only_does_not_produce_a_high_root_hypothesis():
    _, report = diagnostic_case("NameError")
    assert assessment(report)["classification"]["level"] == "LOW"
    assert report["confidence"] is None and not report["hypotheses"]
    assert report["next_action"] == "collect_information"


def test_independent_stream_conflict_abstains():
    _, report = diagnostic_case(stdout="ZeroDivisionError: division by zero")
    assert report["failure_class"] == "unknown" and report["confidence"] is None
    assert report["next_action"] == "collect_information"
    assert assessment(report)["conflicts"]


def test_no_stderr_uses_existing_test_observation_without_invented_location():
    case = {"test_id": "test_add", "status": "error", "error_type": "NameError",
            "message": "name 'missing' is not defined", "location": None}
    _, report = diagnostic_case("", cases=[case], outcome="failed", stage="test")
    assert report["failure_class"] == "runtime_error"
    assert assessment(report)["classification"]["level"] == "HIGH"
    assert report["confidence"] < 0.5


def test_failed_execution_without_exception_remains_unknown():
    _, report = diagnostic_case("")
    assert report["failure_class"] == "unknown"
    assert report["confidence"] is None and not report["hypotheses"]
    assert assessment(report)["root_cause"]["level"] == "UNKNOWN"


def test_parser_raw_disagreement_forces_conservative_assessment():
    request, report = diagnostic_case()
    payload = request["payload"]
    paths = known_workspace_paths(payload)
    sources = evidence_sources(payload["failure_source"], report["evidence_refs"])
    parsed = parse_sources(sources, known_paths=paths)
    parsed["records"][0]["line"] = 777
    result = assess(payload, report, sources, parsed, known_paths=paths)
    assert result["failure_class"] == "unknown" and result["confidence"] is None
    assert not assessment(result)["parsed_matches_raw"]
    assert result["failure_source"] == payload["failure_source"]


def test_environment_state_is_preserved_despite_code_error_log():
    _, report = diagnostic_case(status="infrastructure_error", outcome="not_run", stage="environment")
    assert report["failure_class"] == "environment_error" and report["next_action"] == "fix_environment"
    assert report["confidence"] is None and assessment(report)["conflicts"]


def test_truncated_trace_cannot_establish_full_root_cause():
    request, _ = diagnostic_case()
    request["payload"]["failure_source"]["execution_result"]["stderr"]["truncated"] = True
    report = diagnose(request)["diagnosis_report"]
    assert report["confidence"] is None and report["next_action"] == "collect_information"


def test_linked_chain_selects_terminal_exception_instead_of_first_keyword():
    text = 'ImportError: cannot import name adapter\nThe above exception was the direct cause of the following exception:\nTraceback (most recent call last):\n  File "src/main.py", line 3, in add\nValueError: configuration rejected'
    _, report = diagnostic_case(text)
    assert report["failure_class"] == "runtime_error" and report["raw_failure_class"] == "ValueError"
    assert "ValueError" in report["root_cause"]


def test_test_file_origin_does_not_authorize_implementation_repair():
    _, report = diagnostic_case(TRACE.replace("src/main.py", "tests/test_main.py"), stage="test")
    assert report["failure_domain"] == "test" and report["next_action"] == "collect_information"
    assert not report["suggestions"]


def test_quoted_error_keyword_does_not_become_observed_exception():
    _, report = diagnostic_case("INFO: this example contains the string NameError")
    assert report["failure_class"] == "unknown" and report["confidence"] is None


def test_legacy_rule_confidence_is_unchanged_for_existing_callers():
    assert make_rule_decision(error_log="NameError: name 'missing' is not defined").confidence == 0.75


def test_infrastructure_status_cannot_be_erased_by_conflicting_passed_outcome():
    _, report = diagnostic_case(status="infrastructure_error", outcome="passed", stage="environment")
    assert report["failure_class"] == "environment_error" and report["next_action"] == "fix_environment"
    assert report["confidence"] is None
    assert "TEST_OUTCOME_AND_EXECUTION_STATUS_DISAGREE" in assessment(report)["conflicts"]


def test_explicit_timeout_retains_repair_action_without_claiming_specific_root():
    _, report = diagnostic_case("TimeoutExpired: timed out after 1 second", status="timeout")
    assert report["failure_class"] == "timeout" and report["next_action"] == "repair"
    assert report["confidence"] <= 0.4
