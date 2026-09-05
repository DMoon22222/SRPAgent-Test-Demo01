"""Observable state for model-directed SRP repair attempts."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from pico.config import provider_env
from pico.workspace import clip

DEFAULT_MAX_REPAIR_ROUNDS = 3
REPEATED_DIAGNOSIS_THRESHOLD = 2
REPAIR_SCHEMA_VERSION = "phase3-v1"


def resolve_max_repair_rounds(value: int | None = None) -> int:
    raw_value: Any = value
    if raw_value is None:
        raw_value = provider_env(
            "PICO_SRP_MAX_REPAIR_ROUNDS",
            default=str(DEFAULT_MAX_REPAIR_ROUNDS),
        )
    try:
        rounds = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("PICO_SRP_MAX_REPAIR_ROUNDS must be an integer") from exc
    if rounds < 1:
        raise ValueError("SRP max repair rounds must be at least 1")
    return rounds


class RepairTrajectory:
    """Record repair evidence without deciding how code should be changed."""

    def __init__(self, state: dict[str, Any] | None, *, max_rounds: int):
        self.max_rounds = resolve_max_repair_rounds(max_rounds)
        defaults = self._default_state()
        if isinstance(state, dict) and state.get("schema_version") == REPAIR_SCHEMA_VERSION:
            defaults.update(copy.deepcopy(state))
        defaults["max_repair_rounds"] = self.max_rounds
        self.state = defaults

    def observe_tool(
        self,
        name: str,
        args: dict[str, Any],
        content: str,
        metadata: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        if name in {"patch_file", "write_file"}:
            self._record_code_change(metadata)
            return content, {}
        if name != "execute_and_diagnose":
            return content, {}
        if metadata.get("tool_status") != "ok":
            return self._record_infrastructure_failure(content, metadata)
        return self._record_diagnosis(args, content, metadata)

    def summary(self) -> dict[str, Any]:
        return {
            "repair_attempts": self.state["repair_attempts"],
            "diagnosis_calls": self.state["diagnosis_calls"],
            "final_execution_status": self.state["final_execution_status"],
            "diagnosis_transitions": copy.deepcopy(
                self.state["diagnosis_transitions"]
            ),
            "repair_succeeded": self.state["repair_succeeded"],
            "repair_round_limit_exceeded": self.state[
                "repair_round_limit_exceeded"
            ],
            "repair_stop_reason": self.state["repair_stop_reason"],
            "repeated_diagnosis": self.state["repeated_diagnosis"],
            "retrieval_requested": self.state["retrieval_requested"],
            "retrieval_queries": list(self.state["retrieval_queries"]),
            "infrastructure_failures": copy.deepcopy(
                self.state["infrastructure_failures"]
            ),
            "pending_patch_paths": list(self.state["pending_patch_paths"]),
            "trajectory": copy.deepcopy(self.state["trajectory"]),
            "max_repair_rounds": self.max_rounds,
        }

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.state)

    def prompt_guidance(self) -> str:
        if self.state.get("repair_round_limit_exceeded"):
            return (
                "The configured repair round limit has been reached. Stop repeating "
                "repairs and summarize the remaining diagnosis."
            )
        if self.state.get("repeated_diagnosis"):
            return (
                "Previous repair attempts produced the same diagnosis. Reconsider "
                "the current approach before applying another similar patch."
            )
        return ""

    def _default_state(self) -> dict[str, Any]:
        return {
            "schema_version": REPAIR_SCHEMA_VERSION,
            "max_repair_rounds": self.max_rounds,
            "repair_attempts": 0,
            "diagnosis_calls": 0,
            "final_execution_status": "",
            "diagnosis_transitions": [],
            "repair_succeeded": False,
            "repair_round_limit_exceeded": False,
            "repair_stop_reason": "",
            "repeated_diagnosis": False,
            "consecutive_same_diagnosis": 0,
            "last_diagnosis": {},
            "pending_patch_paths": [],
            "trajectory": [],
            "retrieval_requested": False,
            "retrieval_queries": [],
            "infrastructure_failures": [],
        }

    def _record_code_change(self, metadata: dict[str, Any]) -> None:
        if metadata.get("tool_status") not in {"ok", "partial_success"}:
            return
        if not metadata.get("workspace_changed"):
            return
        pending = self.state["pending_patch_paths"]
        for path in metadata.get("affected_paths", []):
            normalized = _normalize_path(path)
            if normalized and normalized not in pending:
                pending.append(normalized)

    def _record_infrastructure_failure(
        self,
        content: str,
        metadata: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        error_code = str(metadata.get("tool_error_code", "srp_tool_error"))
        failure = {
            "tool_error_code": error_code,
            "message": clip(content, 500),
        }
        self.state["infrastructure_failures"].append(failure)
        enriched = _load_object(content)
        enriched.update(
            {
                "infrastructureFailure": True,
                "repairIteration": self.state["repair_attempts"],
                "repairGuidance": (
                    "SRP infrastructure failed; retry or inspect service availability. "
                    "Do not treat this as a user-code diagnosis."
                ),
            }
        )
        return json.dumps(enriched, ensure_ascii=False, indent=2), {
            "repair_iteration": self.state["repair_attempts"],
            "diagnosis_recorded": False,
            "infrastructure_failure": True,
        }

    def _record_diagnosis(
        self,
        args: dict[str, Any],
        content: str,
        metadata: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        observation = _load_object(content)
        diagnosis = observation.get("diagnosis")
        if not isinstance(diagnosis, dict):
            diagnosis = {}

        self.state["diagnosis_calls"] += 1
        diagnosed_path = _normalize_path(args.get("path", ""))
        pending = self.state["pending_patch_paths"]
        matched_paths = [path for path in pending if path == diagnosed_path]
        if matched_paths:
            self.state["repair_attempts"] += 1
            self.state["pending_patch_paths"] = [
                path for path in pending if path not in matched_paths
            ]

        status = str(
            metadata.get("execution_status")
            or observation.get("executionStatus")
            or "UNKNOWN"
        )
        current = {
            "execution_status": status,
            "failed_stage": str(
                metadata.get("failed_stage")
                or observation.get("failedStage")
                or ""
            ),
            "error_type": str(
                metadata.get("error_type") or diagnosis.get("errorType") or ""
            ),
            "error_subtype": str(
                metadata.get("error_subtype")
                or diagnosis.get("errorSubtype")
                or ""
            ),
            "suspected_location": str(diagnosis.get("suspectedLocation") or ""),
        }
        fingerprint = diagnosis_fingerprint(current)
        previous = copy.deepcopy(self.state.get("last_diagnosis") or {})
        previous_fingerprint = str(previous.get("fingerprint", ""))
        diagnosis_changed = bool(previous_fingerprint) and (
            previous_fingerprint != fingerprint
        )

        success = bool(observation.get("success")) or status == "SUCCESS"
        if not success and fingerprint == previous_fingerprint:
            self.state["consecutive_same_diagnosis"] += 1
        elif success:
            self.state["consecutive_same_diagnosis"] = 0
        else:
            self.state["consecutive_same_diagnosis"] = 1
        repeated = (
            not success
            and self.state["consecutive_same_diagnosis"]
            >= REPEATED_DIAGNOSIS_THRESHOLD
        )

        if previous_fingerprint:
            self.state["diagnosis_transitions"].append(
                {
                    "from": previous_fingerprint,
                    "to": fingerprint,
                    "changed": diagnosis_changed,
                }
            )

        need_retrieval = bool(diagnosis.get("needRetrieval", False))
        retrieval_query = str(diagnosis.get("retrievalQuery") or "")
        if need_retrieval:
            self.state["retrieval_requested"] = True
            if retrieval_query and retrieval_query not in self.state["retrieval_queries"]:
                self.state["retrieval_queries"].append(retrieval_query)

        limit_exceeded = (
            bool(matched_paths)
            and not success
            and self.state["repair_attempts"] >= self.max_rounds
        )
        if limit_exceeded:
            self.state["repair_round_limit_exceeded"] = True
            self.state["repair_stop_reason"] = "repair_round_limit"
        if success:
            self.state["repair_succeeded"] = True
            self.state["repair_stop_reason"] = ""

        current_with_fingerprint = {**current, "fingerprint": fingerprint}
        entry = {
            "repair_iteration": self.state["repair_attempts"],
            "diagnosis_id": f"diagnosis-{self.state['diagnosis_calls']}",
            **current,
            "diagnosis_fingerprint": fingerprint,
            "patch_affected_paths": matched_paths,
            "workspace_changed": bool(matched_paths),
            "previous_diagnosis": previous,
            "current_diagnosis": current_with_fingerprint,
            "diagnosis_changed": diagnosis_changed,
            "repeated_diagnosis": repeated,
            "success": success,
            "need_retrieval": need_retrieval,
            "retrieval_query": retrieval_query,
        }
        self.state["trajectory"].append(entry)
        self.state["last_diagnosis"] = current_with_fingerprint
        self.state["final_execution_status"] = status
        self.state["repeated_diagnosis"] = repeated

        observation.update(
            {
                "repairIteration": self.state["repair_attempts"],
                "diagnosisFingerprint": fingerprint,
                "diagnosisChanged": diagnosis_changed,
                "repeatedDiagnosis": repeated,
                "repairSucceeded": success,
                "repairRoundLimitExceeded": limit_exceeded,
            }
        )
        if repeated:
            observation["repairGuidance"] = (
                "Previous repair attempts produced the same diagnosis. Reconsider "
                "the current approach before applying another similar patch."
            )
        if limit_exceeded:
            observation["repairStopReason"] = "repair_round_limit"
            observation["repairGuidance"] = (
                "The configured repair round limit has been reached. Stop repeating "
                "repairs and summarize the remaining diagnosis."
            )

        return json.dumps(observation, ensure_ascii=False, indent=2), {
            "repair_iteration": self.state["repair_attempts"],
            "diagnosis_fingerprint": fingerprint,
            "diagnosis_changed": diagnosis_changed,
            "repeated_diagnosis": repeated,
            "repair_round_limit_exceeded": limit_exceeded,
            "repair_succeeded": success,
            "retrieval_requested": need_retrieval,
            "diagnosis_recorded": True,
        }


def diagnosis_fingerprint(diagnosis: dict[str, Any]) -> str:
    fields = (
        "execution_status",
        "failed_stage",
        "error_type",
        "error_subtype",
        "suspected_location",
    )
    return "|".join(str(diagnosis.get(field, "") or "") for field in fields)


def _normalize_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    return Path(raw).as_posix().removeprefix("./")


def _load_object(content: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        return {"message": clip(content, 500)}
    return value if isinstance(value, dict) else {"message": clip(content, 500)}
