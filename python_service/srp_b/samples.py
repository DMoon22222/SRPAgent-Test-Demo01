"""Synthetic public requests with fresh identities and real content hashes."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.utils import canonical, digest, file_entry, files_hash, uid

from .module import DIAGNOSE, EXECUTE, STATIC

SOURCE = "def add(a, b):\n    return a + b\n"
TESTS = "from src.main import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def request(operation=EXECUTE, *, source=SOURCE, tests=TESTS, task_id="sample-task", run_id="sample-run"):
    value = ContractRegistry().fixture(operation)
    deadline = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    value.update(message_id=uid("msg"), request_id=uid("request"), call_id=uid("call"),
                 task_id=task_id, run_id=run_id, trace_id="sample-trace", attempt_id="sample-attempt",
                 deadline_at=deadline)
    p = value["payload"]
    p["call_grant"].update(call_id=value["call_id"], grant_id=uid("grant"), deadline_at=deadline)
    p["budget"]["deadline_at"] = deadline
    code = p["code_artifact"]
    code.update(task_id=task_id, attempt_id=value["attempt_id"], artifact_id="sample-code", revision="r0")
    code["files"] = [file_entry("src/main.py", source)]
    code["dependencies"] = []
    code["content_hash"] = files_hash(code["files"])
    manifest = p.get("build_manifest", p.get("execution_context", {}).get("build_manifest"))
    if manifest:
        manifest.update(entry_point="src/main.py", dependencies=["pytest==8.3.5"],
                        runtime={"name": "python", "version": "3.11"}, test_command=["python", "-m", "pytest", "tests"])
    if "task_spec" in p:
        p["task_spec"].update(task_id=task_id, language="python", runtime={"name": "python", "version": "3.11"},
                              instruction="Implement add(a, b), returning the sum. Fixed tests must remain unchanged.")
    if p.get("test_artifact"):
        p["test_artifact"].update(task_id=task_id, artifact_id="sample-tests")
        p["test_artifact"]["files"] = [file_entry("tests/test_main.py", tests)]
        p["test_artifact"]["test_hash"] = files_hash(p["test_artifact"]["files"])
    if operation == DIAGNOSE:
        p["history_view"].update(task_id=task_id, run_id=run_id, attempt_summaries=[], source_refs=[])
        p["prior_diagnosis_ref"] = None
        c = p["execution_context"]
        c["execution_config_hash"] = digest(canonical({"manifest": c["build_manifest"], "policy": c["execution_policy"]}))
    return value


def sample_request(sample):
    """Rebuild a rejection fixture from public input plus explicit scalar patches.

    Protected facts are never exported. This sample encoding is not a wire format.
    """
    value = deepcopy(sample["request"])
    for change in sample.get("request_patches", []):
        keys = change["pointer"].strip("/").split("/")
        target = value
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = change["value"]
    return value


def diagnostic(fact, original, *, static=False):
    value = request(DIAGNOSE, task_id=original["task_id"], run_id=original["run_id"])
    p = value["payload"]
    p["code_artifact"] = deepcopy(original["payload"]["code_artifact"])
    if original["payload"].get("test_artifact"):
        p["test_artifact"] = deepcopy(original["payload"]["test_artifact"])
    p["input_mode"] = "static_feedback" if static else "feedback_only"
    p["failure_source"] = {"kind": "static" if static else "execution", "static_report" if static else "execution_result": deepcopy(fact)}
    if static:
        p["execution_context"]["build_manifest"] = deepcopy(original["payload"]["build_manifest"])
        c = p["execution_context"]
        c["execution_config_hash"] = digest(canonical({"manifest": c["build_manifest"], "policy": c["execution_policy"]}))
    else:
        p["execution_context"] = deepcopy(fact["execution_context"])
    return value
