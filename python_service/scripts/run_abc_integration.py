"""Reproduce the submitted A/C factories with real B and a DeepSeek C adapter."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import importlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "docs/integration/config.abc-mixed.deepseek.example.json"
RUNTIME_PATHS = {
    "A": ["modules/a"],
    "B": ["python_service/srp_b", "python_service/app/analyzer", "docker/b-local"],
    "C": ["my_c", "reliable_codegen", "contracts"],
}


def git(path, *arguments):
    return subprocess.check_output(
        ["git", "-C", str(path), *arguments], text=True, stderr=subprocess.PIPE,
    ).strip()


def preflight(config):
    """Check local inputs only; do not load credentials, create state or use Docker."""
    if set(config) != {"sources", "provider", "runtime", "image", "output_root"}:
        raise ValueError("Unexpected configuration fields; credentials belong in the environment")
    provider = config["provider"]
    if set(provider) != {"base_url", "model", "api_key_env", "max_calls", "timeout_seconds"}:
        raise ValueError("Provider configuration accepts no credential values")
    if provider["base_url"] != "https://api.deepseek.com":
        raise ValueError("This integration adapter supports the official DeepSeek endpoint only")
    if not provider["model"] or provider["api_key_env"] != "DEEPSEEK_API_KEY":
        raise ValueError("Specify a DeepSeek model and the DEEPSEEK_API_KEY variable name")
    if type(provider["max_calls"]) is not int or not 1 <= provider["max_calls"] <= 4:
        raise ValueError("At most four real model calls are allowed")
    if not 0 < provider["timeout_seconds"] <= 30:
        raise ValueError("Model timeout must be in (0, 30] seconds")
    if not isinstance(config["image"], str) or not config["image"].startswith("sha256:"):
        raise ValueError("Select an existing immutable Docker image ID")
    runtime = config["runtime"]
    if set(runtime) != {"timeout_seconds", "deadline_seconds", "max_repairs", "routing_mode", "budget_limits"}:
        raise ValueError("Unexpected runtime fields")
    if runtime["routing_mode"] != "always_rag" or type(runtime["max_repairs"]) is not int or not 0 <= runtime["max_repairs"] <= 2:
        raise ValueError("This mixed integration uses always_rag and at most two repairs")
    if set(config["sources"]) != {"A", "B", "C"}:
        raise ValueError("Configure the A, B and C source checkouts")
    sources = {}
    for name, entry in config["sources"].items():
        if set(entry) != {"path", "revision"}:
            raise ValueError("Each source requires path and revision")
        source = (ROOT / entry["path"]).resolve()
        baseline = git(source, "rev-parse", "--verify", entry["revision"] + "^{commit}")
        # Later documentation/runner commits are allowed when runtime sources match.
        changed = git(source, "diff", "--name-only", baseline, "--", *RUNTIME_PATHS[name])
        if changed:
            raise ValueError(f"{name} runtime differs from the configured revision")
        sources[name] = {"path": str(source), "revision": baseline, "head": git(source, "rev-parse", "HEAD")}
    output = (ROOT / config["output_root"]).resolve()
    if not output.is_relative_to(ROOT / "python_service/.interop"):
        raise ValueError("Private run records must remain under python_service/.interop")
    dependencies = {name: version(name) for name in ("openai", "jsonschema", "pydantic")}
    return {"sources": sources, "dependencies": dependencies, "output_root": str(output)}


class DeepSeekAdapter:
    """Change provider configuration while preserving C prompts and responses."""

    def __init__(self, provider, secret, calls, protected, save, client_factory):
        self.provider, self.secret, self.calls = provider, secret, calls
        self.protected, self.save, self.client_factory = protected, save, client_factory

    def factory(self, stage):
        def create(**arguments):
            if len(self.calls) >= self.provider["max_calls"]:
                raise RuntimeError("Authorized model call limit reached")
            messages = json.dumps(arguments["messages"], ensure_ascii=False)
            if self.secret in messages or any(marker in messages for marker in self.protected):
                raise RuntimeError("Protected data detected; external request refused")
            arguments.update(model=self.provider["model"], response_format={"type": "json_object"},
                             extra_body={"thinking": {"type": "disabled"}})
            call = {"stage": stage, "status": "submitted", "request": arguments}
            self.calls.append(call)
            self.save()
            try:
                with self.client_factory(api_key=self.secret, base_url=self.provider["base_url"],
                                         max_retries=0, timeout=self.provider["timeout_seconds"]) as client:
                    response = client.chat.completions.create(**arguments)
                call.update(status="completed", response=response.model_dump())
            except Exception as error:
                # Provider errors may echo credentials; retain type/status only.
                call.update(status="failed", error_type=type(error).__name__,
                            http_status=getattr(error, "status_code", None))
                self.save()
                raise RuntimeError(f"DEEPSEEK_{stage}_{call['error_type']}_HTTP_{call['http_status']}") from None
            self.save()
            return response

        def client(**_options):
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

        return client


def collect_result(engine, inputs, protected):
    """Inspect protected final execution locally; export only summary facts."""
    from reliable_codegen.orchestrator import PATHS
    from reliable_codegen.utils import canonical

    requests, responses = [], []
    for event in engine.store.events(engine.run_id, allow_restricted=True):
        kind = event["event_type"]
        refs = event["input_refs"] if kind == "request" else event["output_refs"]
        if refs and kind in {"request", "response"}:
            value = engine.store.get(refs[0], allow_restricted=True)
            (requests if kind == "request" else responses).append(value)
    data = [x["payload"]["data"] for x in responses if x["payload"]["status"] == "completed"]
    executions = [x for x in data if "execution_id" in x]
    diagnoses = [x for x in data if "diagnosis_report" in x]
    patches = [x for x in data if "new_code_artifact" in x]
    public = [x for x in executions if x["purpose"] == "feedback"]
    final = [x for x in executions if x["purpose"] == "final_acceptance"]
    repair_type = engine.registry.operation(PATHS["repair"])["request_type"]
    repairs = [x["payload"]["repair_context"] for x in requests if x["payload_type"] == repair_type]
    expected = {engine.registry.operation(path)["request_type"] for path in PATHS.values()}
    checks = {
        "all_eight_operations": expected <= {x["payload_type"] for x in requests},
        "public_failure_then_pass": [x["test_outcome"] for x in public] == ["failed", "passed"],
        "final_execution_passed": len(final) == 1 and final[0]["test_outcome"] == "passed",
        "diagnosis_did_not_reexecute": len(diagnoses) == 1 and all(
            x["payload"]["usage"]["execution_calls"] == 0 for x in responses
            if x["payload"]["status"] == "completed" and "diagnosis_report" in x["payload"]["data"]),
        "fixed_tests_preserved": bool(public and patches) and all(
            x["test_hash"] == inputs["public_tests"]["test_hash"] for x in public) and all(
            x["preserved_test_hash"] == inputs["public_tests"]["test_hash"] for x in patches),
        "b_failure_reached_c": bool(public) and any(
            x["consumer"] == "C" and x["payload"].get("failure_source", {}).get("execution_result") == public[0]
            for x in requests),
        "b_failure_reached_a_repair": bool(public and repairs) and repairs[0]["failure_source"]["execution_result"] == public[0],
        "hidden_tests_absent_from_a_c": all(not any(marker in canonical(x) for marker in protected)
                                           for x in requests if x["consumer"] in {"A", "C"}),
    }
    return {"checks": checks, "requested_payload_types": [x["payload_type"] for x in requests],
            "executions": [{key: x[key] for key in ("execution_id", "purpose", "test_outcome", "tests_total", "tests_passed")}
                           for x in executions],
            "assessments": [x["evidence_assessment"] for x in data if "evidence_assessment" in x],
            "repair_evidence_ids": [[x["evidence_id"] for x in (ctx.get("evidence_bundle") or {}).get("evidence", [])]
                                    for ctx in repairs]}


def run(config, checked, secret):
    sources = {name: Path(value["path"]) for name, value in checked["sources"].items()}
    sys.path[:0] = [str(sources["C"]), str(sources["A"] / "modules/a"), str(sources["B"] / "python_service")]
    for name, directory in (("reliable_codegen", sources["C"]), ("reliable_a", sources["A"] / "modules/a"),
                            ("srp_b", sources["B"] / "python_service")):
        if not Path(importlib.import_module(name).__file__).resolve().is_relative_to(directory):
            raise RuntimeError("Configured source shadowed by another installation")
    from openai import OpenAI
    from reliable_codegen.orchestrator import Orchestrator, demo_inputs
    from reliable_codegen.transport import build_transport

    root = Path(checked["output_root"]) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root.mkdir(parents=True, exist_ok=False)
    inputs = demo_inputs()
    protected = [inputs["final_tests"]["artifact_id"], inputs["final_tests"]["test_hash"]]
    protected += [entry["content"] for entry in inputs["final_tests"]["files"]]
    runtime = {**config["runtime"], "schema_version": "2.0", "transport": "local", "modules": {
        "A": {"factory": "reliable_a:create_module", "options": {"scenario": "repair_rag", "use_sdk": False}},
        "B": {"factory": "srp_b:create_module", "options": {"state_dir": str(root / "b-state"),
                "image": config["image"], "diagnosis_backend": "rules"}},
        "C": {"factory": "my_c.adapter:create_module", "options": {}},
    }}
    record = {"record_version": "1.0", "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
              "scope": "A Mock; real B Docker/rules; C live DeepSeek decide/assess + Mock retrieval; not M1 acceptance",
              "local_inputs": checked, "config": config, "runtime": runtime,
              "task_id": inputs["task_spec"]["task_id"], "public_test_hash": inputs["public_tests"]["test_hash"],
              "final_test_hash": inputs["final_tests"]["test_hash"], "knowledge_snapshot": inputs["knowledge_snapshot_ref"],
              "context_limitation": "A context profile and evidence tokenizer remain fixture-only",
              "model_calls": []}
    def save():
        text = json.dumps(record, ensure_ascii=False, indent=2)
        if secret in text:
            raise RuntimeError("Credential detected in record; write refused")
        (root / "integration.json").write_text(text + "\n", encoding="utf-8")
    save()
    adapter = DeepSeekAdapter(config["provider"], secret, record["model_calls"], protected, save, OpenAI)
    previous_cwd = Path.cwd()
    try:
        # C's Usage enum lookup is relative to its repository root.
        os.chdir(sources["C"])
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "runtime-provider-adapter"}), \
             patch("my_c.qwen_decision.OpenAI", adapter.factory("decide")), \
             patch("my_c.qwen_assessor.OpenAI", adapter.factory("assess")):
            engine = Orchestrator(build_transport(runtime), root / "o-run",
                                  **{key: runtime[key] for key in ("max_repairs", "routing_mode", "deadline_seconds", "budget_limits")})
            result = engine.run(**inputs)
        record.update(collect_result(engine, inputs, protected), run_summary=result,
                      status="finished", finished_at=datetime.now(timezone.utc).isoformat())
        record["checks"].update(accepted_terminal=result["state"] == "accepted",
                               no_module_errors_or_unknown_usage=not result["module_errors"] and not result["unknown_usage_ids"],
                               authorized_model_call_limit=len(record["model_calls"]) <= config["provider"]["max_calls"])
        record.update(actual_model_request_attempts=len(record["model_calls"]),
                      completed_model_responses=sum(call["status"] == "completed" for call in record["model_calls"]))
        save()
    finally:
        os.chdir(previous_cwd)
    return record, root / "integration.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--run", action="store_true", help="Execute real Docker tests and billable DeepSeek calls")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    checked = preflight(config)
    if not args.run:
        print(json.dumps({"mode": "check_only", **checked}, ensure_ascii=False, indent=2))
        return 0
    secret = os.environ.get(config["provider"]["api_key_env"]) or getpass.getpass("DeepSeek key (hidden): ")
    if not secret:
        raise ValueError("DeepSeek credential is required for --run")
    record, path = run(config, checked, secret)
    print(json.dumps({"record": str(path), "state": record["run_summary"]["state"],
                      "mock": record["run_summary"]["mock"], "checks": record["checks"],
                      "budget_used": record["run_summary"]["budget"]["used"]}, ensure_ascii=False, indent=2))
    return 0 if all(record["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
