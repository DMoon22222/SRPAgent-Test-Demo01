"""Public schema 2.0 B module; all boundaries use independent JSON values."""

from __future__ import annotations

import ast
import json
import sys
import threading
from copy import deepcopy
from datetime import datetime, timezone
from time import monotonic

from reliable_codegen.contracts import ContractError, ContractRegistry
from reliable_codegen.guards import (check_artifact_files, check_execution_cases,
                                     check_public, check_response, check_workspace_files)
from reliable_codegen.transport import TransportError, json_copy
from reliable_codegen.utils import canonical, digest, uid, utcnow

from . import __version__
from .diagnosis import diagnose
from .state import Journal, StateConflict

STATIC = "/api/v2/validate/static"
EXECUTE = "/api/v2/execute"
DIAGNOSE = "/api/v2/diagnose"
OPERATIONS = (STATIC, EXECUTE, DIAGNOSE)


class Blocked(ContractError):
    pass


class BModule:
    def __init__(self, state_dir=".interop/local-v2", image="srp-b-python:0.3.0",
                 max_payload_bytes=2 * 1024 * 1024, *, runner=None):
        if type(max_payload_bytes) is not int or not 1 <= max_payload_bytes <= 2 * 1024 * 1024:
            raise ValueError("max_payload_bytes must be between 1 and 2097152")
        if not isinstance(image, str) or not image or image.startswith("-"):
            raise ValueError("A Docker image name or digest is required")
        from .sandbox import DockerRunner

        self.registry = ContractRegistry()
        self.journal = Journal(state_dir)
        self.runner = runner if runner is not None else DockerRunner(image=image)
        self.image, self.max_payload_bytes = image, max_payload_bytes
        self._bindings = threading.local()
        self._lock = threading.RLock()

    def capabilities(self):
        result = {
            "service_name": "B", "schema_version": "2.0", "schema_versions": ["2.0"],
            "operations": list(OPERATIONS), "supported_languages": ["python"],
            "supported_runtimes": [], "max_payload_bytes": self.max_payload_bytes,
            "supports_async": False, "supported_diagnosis_modes": ["static_feedback", "feedback_only"],
            "supported_routing_phases": [], "context_profiles": [], "artifact_resolver_keys": ["local-store"],
            "execution_guarantees": {"backend": "docker", "host_target_execution": False,
                                      "unsupported_policies": "rejected", "runtime": "observed per execution"},
            "extensions": {"srp_b": {"implementation_version": __version__, "diagnosis": "rule_based",
                                       "model_calls": 0, "configured_image": self.image,
                                       "completed_replay": "durable", "pending_replay": "outcome_unknown"}},
        }
        self.registry.validate("CapabilityDescriptor", result)
        return json_copy(result)

    def bind_artifact_resolver(self, resolver_or_none):
        self._bindings.resolver = resolver_or_none

    def resolve_fact(self, reference, *, allow_restricted=False):
        """Explicit local recovery tool; consumers normally resolve facts via O."""
        self.registry.validate("ArtifactRef", reference)
        return self.journal.resolve(reference, allow_restricted=allow_restricted)

    def _transport_error(self, code, request, status=422):
        request = request if type(request) is dict else {}
        def identity(key):
            value = request.get(key)
            return value if type(value) is str and 1 <= len(value) <= 128 else None
        result = {
            "schema_version": "2.0", "request_id": identity("request_id"), "trace_id": identity("trace_id"),
            "created_at": utcnow(), "payload_type": "ModuleError",
            "error": {"error_code": code, "message": code, "retryable": False, "stage": "boundary",
                      "observed_at": utcnow(), "details": {}, "fallback_reason": None,
                      "partial_result_ref": None, "cause_ref": None, "failed_call_id": identity("call_id")},
        }
        return TransportError(code, response=result, status_code=status, outcome_unknown=False)

    def call(self, operation, request):
        try:
            snapshot = json_copy(request)
            if operation not in OPERATIONS:
                raise ContractError("UNKNOWN_OPERATION")
            self.registry.validate_request(operation, snapshot)
            if len(canonical(snapshot).encode("utf-8")) > self.max_payload_bytes:
                raise ContractError("PAYLOAD_TOO_LARGE")
            if snapshot["visibility"] == "public":
                check_public(snapshot)
            elif operation != EXECUTE or snapshot["payload"]["purpose"] != "final_acceptance":
                raise ContractError("PROTECTED_OPERATION")
        except (ValueError, TypeError, KeyError, RecursionError):
            raise self._transport_error("CONTRACT_INVALID", request) from None
        with self._lock:
            try:
                replay, response = self.journal.begin(operation, snapshot)
            except StateConflict as error:
                raise self._transport_error(str(error), snapshot, 409) from None
            if replay == "completed":
                return json_copy(response)
            started = monotonic()
            counters = {"execution_calls": 0}
            if replay == "pending":
                return self._response(operation, snapshot, started, counters, error="OUTCOME_UNKNOWN", unknown=True)
            partial = None
            try:
                timeout = self._authorize(snapshot)
                self._validate_payload(operation, snapshot)
                self.journal.freeze(snapshot)
                if operation == STATIC:
                    data = self._static(snapshot)
                    self.journal.save(data, "StaticCheckReport", data["report_id"])
                elif operation == EXECUTE:
                    data = self._execute(snapshot, min(timeout, self._authorize(snapshot)), counters)
                    self.journal.save(data, "ExecutionResult", data["execution_id"], snapshot["visibility"])
                else:
                    source = snapshot["payload"]["failure_source"]
                    static = source["kind"] == "static"
                    fact = source["static_report" if static else "execution_result"]
                    partial = self.journal.save(fact, "StaticCheckReport" if static else "ExecutionResult",
                                                fact["report_id" if static else "execution_id"])
                    prior, logs = self._context(snapshot)
                    data = diagnose(snapshot, prior=prior, logs=logs)
                    self.journal.save(data["diagnosis_report"], "DiagnosisReport", data["diagnosis_report"]["diagnosis_id"])
                response = self._response(operation, snapshot, started, counters, data=data)
            except Blocked as error:
                response = self._response(operation, snapshot, started, counters, blocked=str(error))
            except (ContractError, ValueError, KeyError) as error:
                # Messages are stable identifiers, never source/log/SDK exception text.
                code = str(error) if isinstance(error, StateConflict) else "INPUT_INVARIANT_VIOLATION"
                response = self._response(operation, snapshot, started, counters, error=code, partial=partial)
            except Exception:
                response = self._response(operation, snapshot, started, counters,
                                          error="DIAGNOSIS_FAILED" if operation == DIAGNOSE else "OPERATION_FAILED",
                                          partial=partial, unknown=operation == EXECUTE)
            self.registry.validate_response(operation, response)
            check_response(snapshot, response)
            if snapshot["visibility"] == "public":
                check_public(response)
            self.journal.finish(operation, snapshot, response)
            return json_copy(response)

    @staticmethod
    def _authorize(request):
        payload = request["payload"]
        grant, budget = payload["call_grant"], payload["budget"]
        if (grant["budget_id"], grant["budget_revision"]) != (budget["budget_id"], budget["revision"]):
            raise Blocked("GRANT_BUDGET_MISMATCH")
        for key in budget["limits"]:
            expected = max(0, budget["limits"][key] - budget["used"][key] - budget["reserved"][key])
            if budget["remaining"][key] != expected or budget["used"][key] > budget["limits"][key]:
                raise Blocked("INVALID_BUDGET_SNAPSHOT")
        for key in ("model_calls", "retrieval_calls", "execution_calls"):
            if grant["max_" + key] > budget["reserved"][key] + budget["remaining"][key]:
                raise Blocked("GRANT_EXCEEDS_BUDGET")
        if grant["max_input_tokens"] + grant["max_output_tokens"] > budget["reserved"]["tokens"] + budget["remaining"]["tokens"]:
            raise Blocked("GRANT_EXCEEDS_BUDGET")
        if request["payload_type"] == "ExecutionRequest" and grant["max_execution_calls"] < 1:
            raise Blocked("EXECUTION_NOT_AUTHORIZED")
        deadlines = [request["deadline_at"], grant["deadline_at"], budget["deadline_at"]]
        timeout = min((datetime.fromisoformat(d.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() for d in deadlines)
        timeout = min(timeout, budget["remaining"]["wall_time_ms"] / 1000)
        if timeout <= 0:
            raise Blocked("DEADLINE_EXCEEDED")
        return timeout

    def _validate_payload(self, operation, request):
        payload, task = request["payload"], request["task_id"]
        code, tests = payload["code_artifact"], payload.get("test_artifact")
        check_artifact_files(code)
        if code["task_id"] != task or code["attempt_id"] != request["attempt_id"]:
            raise ContractError("Code identity mismatch")
        if code["language"] != "python" or len(code["files"]) != 1:
            raise Blocked("ONLY_PYTHON_SINGLE_FILE_SUPPORTED")
        if code["dependencies"]:
            raise Blocked("TASK_DEPENDENCIES_NOT_SUPPORTED")
        try:
            tree = ast.parse(code["files"][0]["content"])
        except SyntaxError:
            tree = None  # Syntax failure is reported by the static capability.
        if tree:
            imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
            imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
            if imports - sys.stdlib_module_names - {"__future__"}:
                raise Blocked("NON_STDLIB_TASK_IMPORT")
        if tests:
            check_artifact_files(tests)
            if tests["task_id"] != task:
                raise ContractError("Test identity mismatch")
        manifest = payload.get("build_manifest", payload.get("execution_context", {}).get("build_manifest"))
        if manifest:
            check_artifact_files(manifest)
            if manifest["language"] != "python" or manifest["runtime"]["name"] != "python":
                raise Blocked("ONLY_PYTHON_SUPPORTED")
            if operation != STATIC and manifest["entry_point"] not in {f["path"] for f in code["files"]}:
                raise ContractError("Missing entry point")
            check_workspace_files(code, tests or {"files": []}, manifest)
        if operation == STATIC:
            if payload["task_spec"]["task_id"] != task:
                raise ContractError("Task identity mismatch")
            if payload["task_spec"]["runtime"] != manifest["runtime"]:
                raise ContractError("Requested runtime mismatch")
        elif operation == EXECUTE:
            final = payload["purpose"] == "final_acceptance"
            if (request["visibility"] == "restricted") != final or tests["kind"] != ("final_hidden" if final else "public"):
                raise ContractError("Execution visibility mismatch")
        else:
            if not tests:
                raise Blocked("TEST_ARTIFACT_REQUIRED_FOR_DIAGNOSIS")
            check_public(payload)
            if payload["input_mode"] not in {"static_feedback", "feedback_only"}:
                raise Blocked("COMBINED_MODE_NOT_SUPPORTED")
            if payload["task_spec"]["task_id"] != task or payload["history_view"]["task_id"] != task or payload["history_view"]["run_id"] != request["run_id"]:
                raise ContractError("Diagnostic context identity mismatch")
            source = payload["failure_source"]
            static = payload["input_mode"] == "static_feedback"
            if source["kind"] != ("static" if static else "execution"):
                raise ContractError("Diagnostic mode mismatch")
            fact = source["static_report" if static else "execution_result"]
            for key, value in {"task_id": task, "attempt_id": request["attempt_id"], "producer": "B",
                               "code_artifact_id": code["artifact_id"], "revision": code["revision"], "code_hash": code["content_hash"]}.items():
                if fact[key] != value:
                    raise ContractError("Failure source identity mismatch")
            context = payload["execution_context"]
            if context["execution_config_hash"] != digest(canonical({"manifest": context["build_manifest"], "policy": context["execution_policy"]})):
                raise ContractError("Execution configuration hash mismatch")
            if not static:
                check_execution_cases(fact)
                if fact["test_hash"] != tests["test_hash"] or fact["test_artifact_id"] != tests["artifact_id"] or fact["execution_context"] != context or fact["execution_config_hash"] != context["execution_config_hash"]:
                    raise ContractError("Failure source tests or environment mismatch")
                for name in ("stdout", "stderr"):
                    if "text" in fact[name] and digest(fact[name]["text"]) != fact[name]["sha256"]:
                        raise ContractError("Log hash mismatch")

    def _context(self, request):
        payload = request["payload"]
        prior = None
        resolver = getattr(self._bindings, "resolver", None)
        refs = payload["history_view"]["source_refs"] + ([payload["prior_diagnosis_ref"]] if payload["prior_diagnosis_ref"] else [])
        resolved = {}
        for reference in refs:
            if resolver is None:
                raise Blocked("AUTHORIZED_ARTIFACT_RESOLVER_REQUIRED")
            try:
                record = json_copy(resolver.resolve(reference))
                self.registry.validate("ArtifactRecord", record)
                if record["artifact_ref"] != reference or digest(record["body_utf8"]) != reference["sha256"]:
                    raise ContractError("Artifact hash mismatch")
                value = json.loads(record["body_utf8"]) if record["content_kind"] == "json" else record["body_utf8"]
                check_public(value)
                if reference["artifact_type"] in self.registry.schemas:
                    self.registry.validate(reference["artifact_type"], value)
                if isinstance(value, dict) and value.get("task_id", request["task_id"]) != request["task_id"]:
                    raise ContractError("Artifact task mismatch")
                resolved[canonical(reference)] = value
            except (ValueError, TypeError, KeyError):
                raise Blocked("AUTHORIZED_CONTEXT_UNAVAILABLE") from None
        if payload["prior_diagnosis_ref"]:
            prior = resolved[canonical(payload["prior_diagnosis_ref"])]
            self.registry.validate("DiagnosisReport", prior)
        logs = {}
        source = payload["failure_source"]
        if source["kind"] == "execution":
            for name in ("stdout", "stderr"):
                stream = source["execution_result"][name]
                if "text" in stream:
                    logs[name] = stream["text"]
                else:
                    if resolver is None:
                        raise Blocked("AUTHORIZED_ARTIFACT_RESOLVER_REQUIRED")
                    record = resolver.resolve(stream["content_ref"])
                    if record["artifact_ref"] != stream["content_ref"] or digest(record["body_utf8"]) != stream["sha256"]:
                        raise ContractError("Referenced log hash mismatch")
                    check_public(record)
                    logs[name] = record["body_utf8"]
        return prior, logs

    def _static(self, request):
        payload = request["payload"]
        code, manifest = payload["code_artifact"], payload["build_manifest"]
        findings = []
        for check in payload["validation_policy"]["checks"]:
            location = None
            if check == "syntax":
                try:
                    version = tuple(int(v) for v in manifest["runtime"]["version"].split(".")[:2])
                    if len(version) != 2 or version[0] != 3 or version > sys.version_info[:2]:
                        raise Blocked("STATIC_RUNTIME_GRAMMAR_UNAVAILABLE")
                    ast.parse(code["files"][0]["content"], filename=code["files"][0]["path"], feature_version=version)
                    status, message = "passed", "Python syntax parsed without executing source."
                except SyntaxError as error:
                    status, message = "failed", f"{type(error).__name__}: {error.msg}"
                    location = {"file": code["files"][0]["path"], "line_start": error.lineno,
                                "line_end": error.end_lineno or error.lineno, "symbol": None}
            elif check == "entry_point":
                present = manifest["entry_point"] in {f["path"] for f in code["files"]}
                status = "passed" if present else "failed"
                message = "Build entry point identifies the supplied source file." if present else "Build entry point is absent from the supplied code artifact."
            elif check == "artifact_integrity":
                status, message = "passed", "Inline file and collection hashes verified."
            else:
                check, status, message = check if check in {"constraints", "permissions"} else "constraints", "unknown", "Requested validation is unsupported; no passing fact was inferred."
            findings.append({"check": check, "status": status, "message": message, "location": location})
        return {"schema_version": "2.0", "created_at": utcnow(), "producer": "B", "report_id": uid("static"),
                "task_id": request["task_id"], "attempt_id": request["attempt_id"],
                "code_artifact_id": code["artifact_id"], "revision": code["revision"], "code_hash": code["content_hash"],
                "status": "failed" if any(f["status"] == "failed" for f in findings) else "blocked" if any(f["status"] == "unknown" for f in findings) else "passed",
                "findings": findings, "policy_version": payload["validation_policy"]["policy_version"]}

    def _execute(self, request, timeout, counters):
        payload = request["payload"]
        code, tests, manifest, policy = (payload[k] for k in ("code_artifact", "test_artifact", "build_manifest", "execution_policy"))
        execution_id = uid("execution")
        observed = self.runner.execute(deepcopy(payload), timeout_seconds=timeout, execution_id=execution_id)
        counters["execution_calls"] = observed.pop("execution_calls")
        context = {"context_id": uid("execution-context"), "build_manifest": deepcopy(manifest),
                   "execution_policy": deepcopy(policy), "execution_config_hash": digest(canonical({"manifest": manifest, "policy": policy})),
                   "requested_runtime": deepcopy(manifest["runtime"]), "actual_runtime": observed.pop("actual_runtime"),
                   "package_versions": observed.pop("package_versions"), "image_digest": observed.pop("image_digest"),
                   "dependency_lock_ref": None, "isolation_guarantees": observed.pop("isolation_guarantees"),
                   "measurement_status": observed.pop("measurement_status")}
        result = {"schema_version": "2.0", "created_at": utcnow(), "producer": "B", "execution_id": execution_id,
                  "task_id": request["task_id"], "attempt_id": request["attempt_id"],
                  "code_artifact_id": code["artifact_id"], "revision": code["revision"], "code_hash": code["content_hash"],
                  "test_artifact_id": tests["artifact_id"], "test_hash": tests["test_hash"],
                  "execution_config_hash": context["execution_config_hash"], "purpose": payload["purpose"],
                  "execution_context": context, "visibility": request["visibility"], **observed}
        self.registry.validate("ExecutionResult", result)
        check_execution_cases(result)
        return result

    def _response(self, operation, request, started, counters, *, data=None, error=None, blocked=None, partial=None, unknown=False):
        usage = {"usage_id": uid("usage"), "call_id": request["call_id"], "parent_call_id": request["parent_call_id"],
                 "input_tokens": 0, "output_tokens": 0, "model_calls": 0, "retrieval_calls": 0,
                 "execution_calls": counters["execution_calls"], "latency_ms": round((monotonic() - started) * 1000, 3),
                 "estimated_cost_usd": None, "measurement_status": "complete", "measurement": "exact",
                 "aggregation": "leaf", "children_usage_ids": [], "notes": ["Local rules only; no model or retrieval was invoked. Cost is not priced."]}
        if unknown or counters["execution_calls"] is None:
            usage.update(execution_calls=None, measurement_status="partial", measurement="unknown")
        module_error = None
        status = "completed"
        if error:
            status, data = "error", None
            module_error = {"error_code": error, "message": error, "retryable": False,
                            "stage": "diagnose" if operation == DIAGNOSE else "execute" if operation == EXECUTE else "static",
                            "observed_at": utcnow(), "details": {}, "fallback_reason": "human_review",
                            "partial_result_ref": partial, "cause_ref": None, "failed_call_id": request["call_id"]}
        elif blocked:
            status, data = "blocked", {"reason": blocked, "missing_fields": [], "questions": [], "handoff_state": "BLOCKED"}
        result = {key: request[key] for key in ("schema_version", "request_id", "call_id", "parent_call_id", "trace_id", "task_id", "run_id", "attempt_id", "visibility")}
        result.update(message_id=uid("msg"), in_reply_to=request["message_id"], producer="B", consumer="O",
                      payload_type=self.registry.operation(operation)["result_type"], created_at=utcnow(),
                      payload={"status": status, "data": data, "error": module_error, "usage": usage, "warnings": []},
                      extensions={"srp_b": {"implementation_version": __version__, "operation": operation}})
        return result
