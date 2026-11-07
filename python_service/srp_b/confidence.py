"""Versioned heuristic confidence; classification is distinct from root cause."""

from __future__ import annotations

from copy import deepcopy

from app.analyzer.error_signal_extractor import make_rule_decision

from .structured_errors import safe_path, validate_parsed, wire_frames

VERSION = "b-confidence-v1"


def _level(score):
    if score is None:
        return "UNKNOWN"
    return "HIGH" if score >= 0.8 else "MEDIUM" if score >= 0.5 else "LOW"


def _category(name):
    if name in {"SyntaxError", "IndentationError", "TabError"}:
        return "syntax_error"
    if name in {"ImportError", "ModuleNotFoundError"}:
        return "dependency_error"
    if name == "AssertionError":
        return "test_failure"
    return "runtime_error"


def assess(payload, report, sources, parsed, *, known_paths=()):
    """Use raw status, linked terminal exceptions and explicit uncertainty caps."""
    result = deepcopy(report)
    static = payload["failure_source"]["kind"] == "static"
    fact = payload["failure_source"]["static_report" if static else "execution_result"]
    extension = result["extensions"]["srp_b"]
    valid = validate_parsed(parsed, sources, known_paths=known_paths)
    records = parsed["records"] if valid else []
    terminals = [item for record in records for item in record["terminal_exceptions"]]
    types = {item["error_type"] for item in terminals}
    incomplete = any(record["input_truncated"] or record["incomplete_stack"] for record in records) or parsed["sources_truncated"]
    conflicts = []
    reasons = []
    class_score, root_score = None, None
    authoritative = None
    if not static:
        authoritative = {"infrastructure_error": "environment_error", "timeout": "timeout", "oom": "resource_limit",
                         "policy_rejected": "unknown"}.get(fact["execution_status"])
    failed = fact["status"] != "passed" if static else (fact["test_outcome"] != "passed" or fact["execution_status"] != "completed")
    if not static and fact["test_outcome"] == "passed" and fact["execution_status"] != "completed":
        conflicts.append("TEST_OUTCOME_AND_EXECUTION_STATUS_DISAGREE")
    frame_types = [frame for record in records for frame in record["stack_frames"]]
    has_location = any(frame["line"] is not None for frame in frame_types)
    if len(types) > 1:
        conflicts.append("INDEPENDENT_TERMINAL_EXCEPTIONS_DISAGREE")
    if authoritative is not None and types:
        expected_types = {
            "timeout": {"TimeoutError", "TimeoutExpired"},
            "resource_limit": {"MemoryError"},
            "environment_error": {"EnvironmentError", "OSError", "ConnectionError"},
            "unknown": set(),
        }[authoritative]
        if types - expected_types:
            conflicts.append("EXECUTION_STATUS_AND_LOG_EXCEPTION_DISAGREE")
    if not valid:
        conflicts.append("PARSED_FACTS_DO_NOT_MATCH_RAW_EVIDENCE")
    if not failed:
        if types:
            conflicts.append("PASSING_FACT_WITH_STALE_ERROR_LOG")
        result.update(failure_class="none", failure_domain="none", failure_stage="none",
                      root_cause=None, confidence=None, hypotheses=[], evidence_refs=[],
                      retrieval_hint="not_needed", next_action="none")
        class_score = 0.95
        reasons.append("RAW_TESTS_PASSED")
    elif static and fact["status"] == "failed":
        class_score = 0.95
        root_score = 0.8 if has_location and valid and not incomplete else 0.4
        reasons.append("EXPLICIT_STATIC_FINDING")
    elif authoritative is not None:
        result["failure_class"] = authoritative
        class_score = 0.95
        reasons.append("RAW_EXECUTION_STATUS")
        if authoritative == "environment_error":
            result["next_action"] = "fix_environment"
            if conflicts:
                result["root_cause"] = None
            else:
                root_score = 0.35 if result["evidence_refs"] else None
        elif fact["execution_status"] == "policy_rejected":
            class_score = None
            result["next_action"] = "stop"
            result["root_cause"] = None
        elif conflicts or not terminals:
            result.update(root_cause=None, next_action="collect_information")
        else:
            root_score = 0.4
            if authoritative == "resource_limit":
                result["root_cause"] = "The execution backend reported an out-of-memory termination; the allocation cause is not established."
    elif conflicts:
        result.update(failure_class="unknown", root_cause=None, next_action="collect_information", retrieval_hint="unknown")
    elif terminals:
        terminal = terminals[-1]
        name, message = terminal["error_type"], terminal["error_message"]
        result["failure_class"] = _category(name)
        rule = make_rule_decision(error_log=name + ": " + message)
        result["raw_failure_class"] = rule.errorSubtype if rule.confidence else name
        result["root_cause"] = rule.explanation if rule.confidence else f"The parsed terminal exception is {name}: {message}. Its deeper cause remains a hypothesis."
        result["retrieval_hint"] = "needed" if rule.needRetrieval else "not_needed"
        result["query_hints"] = [rule.retrievalQuery] if rule.needRetrieval and rule.retrievalQuery else []
        class_score = 0.9 if message else 0.45
        root_score = 0.65 if has_location else 0.35
        if any(len(record["exception_chain"]) > 1 for record in records):
            root_score = min(root_score, 0.5)
            reasons.append("LINKED_EXCEPTION_CHAIN")
        reasons.append("EXPLICIT_TERMINAL_EXCEPTION" if message else "EXCEPTION_KEYWORD_ONLY")
        project_frames = [frame for frame in frame_types if frame["file"] in known_paths]
        if project_frames and name != "AssertionError" and all(frame["file"].startswith("tests/") for frame in project_frames):
            result.update(failure_domain="test", next_action="collect_information",
                          root_cause="The exception is reported in a test file; review the test/fixture before attributing it to implementation code.")
            root_score = min(root_score, 0.5)
            reasons.append("TEST_FILE_ORIGIN")
        if not message and not (name == "AssertionError" and fact["test_outcome"] == "failed"):
            result.update(root_cause=None, next_action="collect_information")
            root_score = None
    elif not static and fact["test_outcome"] == "failed" and fact["test_case_results"]:
        result["failure_class"] = "test_failure"
        class_score = 0.8
        reasons.append("RAW_FAILED_TEST_WITHOUT_SPECIFIC_CAUSE")
    else:
        result.update(failure_class="unknown", root_cause=None, next_action="collect_information", retrieval_hint="unknown")
        reasons.append("INSUFFICIENT_SPECIFIC_EVIDENCE")
    if incomplete and failed and authoritative not in {"environment_error", "unknown"}:
        result.update(root_cause=None, next_action="collect_information")
        root_score = None
        if class_score is not None:
            class_score = min(class_score, 0.55)
        reasons.append("INCOMPLETE_OR_TRUNCATED_EVIDENCE")
    if not valid:
        root_score = None
        result.update(root_cause=None)
        if authoritative is None:
            class_score = None
            result.update(failure_class="unknown", next_action="collect_information")
    if conflicts:
        root_score = None
        if authoritative is None and failed:
            class_score = None
    if not result["evidence_refs"] or result["root_cause"] is None:
        root_score = None
    if result["failure_class"] == "unknown":
        result["query_hints"] = []
    if result["next_action"] != "repair":
        result["suggestions"] = []
    result["confidence"] = root_score
    if result["root_cause"] is None:
        result["hypotheses"] = []
    else:
        for hypothesis in result["hypotheses"]:
            hypothesis.update(statement=result["root_cause"], confidence=root_score)
    locations = deepcopy(result["locations"])
    for location in locations:
        if location["file"]:
            location["file"] = safe_path(location["file"], known_paths)
    for frame in wire_frames(parsed) if valid else []:
        if frame["location"] not in locations:
            locations.append(frame["location"])
    result["locations"] = locations
    for hypothesis in result["hypotheses"]:
        hypothesis["locations"] = deepcopy(locations)
    uncertain = bool(conflicts or incomplete or result["next_action"] == "collect_information")
    if uncertain:
        result["local_context_sufficiency"] = "insufficient"
        result["context_gap"] = [{"description": "Incomplete, conflicting or non-specific diagnostic evidence",
                                   "symbols": [], "required_versions": [],
                                   "missing_information": conflicts or ["Complete exception and source context"]}]
    extension["structured_errors"] = deepcopy(parsed) if valid else {"layer": "parsed_facts", "parse_status": "invalid", "records": []}
    extension["confidence_assessment"] = {
        "version": VERSION, "meaning": "heuristic_evidence_score_not_calibrated_probability",
        "classification": {"score": class_score, "level": _level(class_score), "reasons": reasons},
        "root_cause": {"score": root_score, "level": _level(root_score),
                       "reasons": reasons + (["CONFLICT_REQUIRES_ABSTENTION"] if conflicts else [])},
        "conflicts": conflicts, "parsed_matches_raw": valid,
        "basis": [{"artifact_id": source["reference"]["artifact_id"], "pointer": source["reference"]["pointer"],
                   "raw_fact_sha256": source["raw_fact_sha256"]} for source in sources[:64]],
    }
    return result
