"""Independent Docker runner with bounded I/O, immutable image IDs and cleanup.

Only the supplied workspace enters the container. No target code, conftest,
test module, or generated import is evaluated by this host process.
"""

from __future__ import annotations

import json
import re
import subprocess
import stat
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from reliable_codegen.guards import check_artifact_files
from reliable_codegen.utils import digest

OUTPUT_LIMIT = 1024 * 1024
RETAIN_BYTES = 32 * 1024
REPORT_LIMIT = 2 * 1024 * 1024
PROBE = (
    "import sys,json,importlib.metadata as m; "
    "print(json.dumps({'runtime':{'name':'python','version':sys.version.split()[0]},"
    "'packages':[{'name':'pytest','version':m.version('pytest'),'source':'observed'}]}))"
)


@dataclass
class Command:
    returncode: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    timeout: bool = False
    overflow: bool = False


def bounded_command(args, timeout, *, retain=RETAIN_BYTES, hard_limit=OUTPUT_LIMIT):
    """Drain pipes continuously, retain a fixed prefix, stop excessive output."""
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    buffers = [bytearray(), bytearray()]
    lengths = [0, 0]
    lock, overflow = threading.Lock(), threading.Event()

    def drain(stream, index):
        try:
            while chunk := stream.read(4096):
                with lock:
                    lengths[index] += len(chunk)
                    room = max(0, retain - len(buffers[index]))
                    buffers[index].extend(chunk[:room])
                    if sum(lengths) > hard_limit:
                        overflow.set()
        finally:
            stream.close()

    readers = [threading.Thread(target=drain, args=(stream, i), daemon=True)
               for i, stream in enumerate((process.stdout, process.stderr))]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + max(0, timeout)
    timed_out = False
    while process.poll() is None:
        if overflow.is_set() or time.monotonic() >= deadline:
            timed_out = not overflow.is_set()
            process.kill()
            break
        time.sleep(0.01)
    process.wait(timeout=3)
    for reader in readers:
        reader.join(timeout=3)
    return Command(process.returncode, bytes(buffers[0]), bytes(buffers[1]),
                   lengths[0] > retain, lengths[1] > retain, timed_out, overflow.is_set())


def log_stream(content=b"", truncated=False):
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    return {"text": text, "sha256": digest(text), "truncated": truncated}


def relative_path(value):
    check_artifact_files({"files": [{"path": value, "content": "", "sha256": digest("")}]})
    return value


def empty_observation(status="infrastructure_error", message="Sandbox environment is unavailable."):
    return {
        "execution_status": status, "test_outcome": "not_run", "exit_code": None,
        "tests_passed": None, "tests_total": None, "failure_stage": "environment",
        "stdout": log_stream(), "stderr": log_stream(message),
        "resource_usage": {"wall_time_ms": None, "cpu_time_ms": None, "peak_memory_bytes": None,
                           "measurement_status": "unknown", "notes": ["Target resource measurements are unavailable."]},
        "test_case_results": [], "traceback": [], "signal": None,
        "termination_reason": "policy" if status == "policy_rejected" else "infrastructure",
        "actual_runtime": None, "package_versions": [], "image_digest": None,
        "isolation_guarantees": {}, "measurement_status": "unknown", "execution_calls": 0,
    }


def parse_cases(xml_bytes, oracle):
    if not xml_bytes or len(xml_bytes) > REPORT_LIMIT or b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
        raise ValueError("INVALID_TEST_REPORT")
    root = ET.fromstring(xml_bytes)
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("INVALID_TEST_REPORT")
    cases, ids = [], set()
    for node in root.iter("testcase"):
        identity = "::".join(filter(None, [node.get("classname"), node.get("name")])) or "unnamed"
        if len(identity) > 128:
            identity = identity[:100] + "-" + digest(identity)[:20]
        if identity in ids:
            raise ValueError("DUPLICATE_TEST_REPORT_ID")
        ids.add(identity)
        failure = next((c for c in node if c.tag in {"failure", "error"}), None)
        status = "error" if failure is not None and failure.tag == "error" else "failed" if failure is not None else "skipped" if node.find("skipped") is not None else "passed"
        message = ((failure.get("message") or "") + "\n" + (failure.text or "")).strip()[:4096] if failure is not None else None
        location = None
        if node.get("file"):
            line = node.get("line")
            line = int(line) + 1 if line and line.isdigit() else None
            location = {"file": node.get("file"), "line_start": line, "line_end": line, "symbol": node.get("name")}
        cases.append({"test_id": identity, "status": status, "oracle_level": oracle,
                      "expected": None, "actual": None,
                      "error_type": failure.get("type") if failure is not None else None,
                      "message": message, "location": location})
    if len(cases) > 5000:
        raise ValueError("TEST_REPORT_TOO_LARGE")
    return cases


def read_report(workspace):
    scratch = workspace / "tmp"
    report = scratch / "b-junit.xml"
    info = report.lstat()
    if not stat.S_ISREG(info.st_mode) or report.is_symlink() or not report.resolve().is_relative_to(scratch.resolve()):
        raise ValueError("INVALID_TEST_REPORT_PATH")
    if info.st_size > REPORT_LIMIT:
        raise ValueError("TEST_REPORT_TOO_LARGE")
    with report.open("rb") as stream:
        return stream.read(REPORT_LIMIT + 1)


class DockerRunner:
    def __init__(self, image, command=bounded_command):
        self.image, self.command = image, command

    @staticmethod
    def validate_policy(payload):
        policy, manifest = payload["execution_policy"], payload["build_manifest"]
        if policy["network_policy"] != "disabled" or not policy["root_read_only"]:
            raise ValueError("POLICY_NOT_SUPPORTED")
        if any(policy[key] <= 0 for key in ("timeout_ms", "memory_mb", "cpu_limit", "max_processes")):
            raise ValueError("INVALID_RESOURCE_POLICY")
        if policy["max_processes"] < 2:
            raise ValueError("POLICY_REQUIRES_INIT_AND_TARGET_PROCESS")
        writes = policy["allowed_write_paths"]
        if "tmp" not in writes or len(set(writes)) != len(writes):
            raise ValueError("POLICY_REQUIRES_TMP_WRITE_PATH")
        protected = [f["path"] for obj in (payload["code_artifact"], payload["test_artifact"], manifest)
                     for f in obj.get("files", obj.get("supporting_files", []))]
        for scope in writes:
            relative_path(scope)
            if any(p == scope or p.startswith(scope + "/") or scope.startswith(p + "/") for p in protected):
                raise ValueError("WRITABLE_ARTIFACT_PATH")
            if any(other != scope and (scope.startswith(other + "/") or other.startswith(scope + "/")) for other in writes):
                raise ValueError("OVERLAPPING_WRITE_PATHS")
        command = manifest["test_command"]
        if len(command) < 4 or command[:3] not in (["python", "-m", "pytest"], ["python3", "-m", "pytest"]):
            raise ValueError("TEST_COMMAND_NOT_SUPPORTED")
        tests = [f["path"] for f in payload["test_artifact"]["files"]]
        for target in command[3:]:
            relative_path(target)
            if target.startswith("-") or not any(p == target or p.startswith(target.rstrip("/") + "/") for p in tests):
                raise ValueError("UNAUTHORIZED_TEST_TARGET")
        for dependency in manifest["dependencies"]:
            if not re.fullmatch(r"pytest==[0-9]+\.[0-9]+\.[0-9]+", dependency):
                raise ValueError("DEPENDENCY_NOT_SUPPORTED")

    @staticmethod
    def create_args(name, image, policy, workdir=None):
        args = ["docker", "create", "--name", name, "--pull=never", "--init", "--network", "none", "--read-only",
                "--memory", f"{policy['memory_mb']}m", "--memory-swap", f"{policy['memory_mb']}m",
                "--cpus", str(policy["cpu_limit"]), "--pids-limit", str(policy["max_processes"]),
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
                "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONUNBUFFERED=1",
                "--env", "PYTHONNOUSERSITE=1", "--env", "PYTHONPATH=/workspace",
                "--env", "TMPDIR=/workspace/tmp", "--env", "HOME=/workspace/tmp",
                "--workdir", "/workspace", "--entrypoint", "python3"]
        if workdir:
            args += ["--mount", f"type=bind,source={workdir},target=/workspace,readonly"]
        for path in policy["allowed_write_paths"]:
            args += ["--tmpfs", f"/workspace/{path}:rw,nosuid,nodev,noexec,size={min(policy['memory_mb'], 64)}m,mode=1777"]
        if workdir:
            # Only the report file persists. Other temporary writes stay on
            # Linux tmpfs (Windows bind mounts lack POSIX unlink semantics).
            source = Path(workdir) / "tmp" / "b-junit.xml"
            args += ["--mount", f"type=bind,source={source},target=/workspace/tmp/b-junit.xml"]
        return args + [image]

    def _cleanup(self, name):
        try:
            removed = self.command(["docker", "rm", "--force", name], 5)
            if removed.returncode == 0 and not removed.timeout:
                return True
            # A create request may fail before the named container exists.
            inspected = self.command(["docker", "inspect", name], 3)
            return inspected.returncode != 0 and b"No such object" in inspected.stderr
        except (OSError, subprocess.SubprocessError):
            return False

    def execute(self, payload, *, timeout_seconds, execution_id):
        observation = empty_observation()
        try:
            self.validate_policy(payload)
        except (ValueError, TypeError):
            observation = empty_observation("policy_rejected", "Execution policy or build command is unsupported.")
            observation["failure_stage"] = "environment"
            return observation
        started = time.monotonic()
        deadline = started + timeout_seconds

        def run(args, *, command_timeout=10, **kwargs):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("EXECUTION_DEADLINE_EXCEEDED")
            return self.command(args, min(remaining, command_timeout), **kwargs)

        policy = payload["execution_policy"]
        name = "srp-b-" + execution_id
        probe_name = name + "-probe"
        target_created, probe_created = False, False
        temporary = None
        try:
            inspected = run(["docker", "image", "inspect", "--format", "{{.Id}}", self.image])
            image_id = inspected.stdout.decode().strip()
            if inspected.returncode or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                return observation
            observation["image_digest"] = image_id
            probe_created = True  # Also clean up if the create reply is lost.
            probe = run(self.create_args(probe_name, image_id, policy) + ["-c", PROBE])
            if probe.returncode:
                return observation
            probe = run(["docker", "start", "--attach", probe_name])
            if probe.returncode or probe.timeout or probe.overflow:
                return observation
            environment = json.loads(probe.stdout)
            actual = environment["runtime"]
            observation.update(actual_runtime=actual, package_versions=environment["packages"], measurement_status="partial")
            requested = payload["build_manifest"]["runtime"]
            if actual["name"] != requested["name"] or not (actual["version"] == requested["version"] or actual["version"].startswith(requested["version"] + ".")):
                observation["stderr"] = log_stream("Observed Python runtime does not match the requested runtime.")
                return observation
            installed = {p["name"]: p["version"] for p in environment["packages"]}
            if any(installed.get(dep.split("==")[0]) != dep.split("==")[1] for dep in payload["build_manifest"]["dependencies"]):
                observation["stderr"] = log_stream("Observed test runner does not match the build manifest.")
                return observation
            if not self._cleanup(probe_name):
                observation["stderr"] = log_stream("Runtime probe cleanup could not be confirmed.")
                return observation
            probe_created = False
            temporary = tempfile.TemporaryDirectory(prefix="srp-b-")
            workspace = Path(temporary.name).resolve()
            workspace.chmod(0o755)
            for artifact in (payload["code_artifact"], payload["test_artifact"], payload["build_manifest"]):
                for file in artifact.get("files", artifact.get("supporting_files", [])):
                    path = workspace.joinpath(*PurePosixPath(file["path"]).parts)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(file["content"], encoding="utf-8", newline="")
                    path.chmod(0o644)
            for directory in workspace.rglob("*"):
                if directory.is_dir():
                    directory.chmod(0o755)
            for path in policy["allowed_write_paths"]:
                writable = workspace.joinpath(*PurePosixPath(path).parts)
                writable.mkdir(parents=True, exist_ok=True)
                writable.chmod(0o777)
            report_path = workspace / "tmp" / "b-junit.xml"
            report_path.write_bytes(b"")
            report_path.chmod(0o666)
            args = self.create_args(name, image_id, policy, workspace)
            args += ["-m", "pytest", "-q", "--color=no", "--tb=short", "-p", "no:cacheprovider",
                     "--junitxml=/workspace/tmp/b-junit.xml", *payload["build_manifest"]["test_command"][3:]]
            target_created = True
            created = run(args)
            if created.returncode:
                return observation
            observation["execution_calls"] = None  # Until Docker confirms whether it started.
            attached = run(["docker", "start", "--attach", name], command_timeout=policy["timeout_ms"] / 1000)
            observation["stdout"] = log_stream(attached.stdout, attached.stdout_truncated)
            observation["stderr"] = log_stream(attached.stderr, attached.stderr_truncated)
            if attached.timeout or attached.overflow:
                state_reply = self.command(["docker", "inspect", "--format", "{{json .State}}", name], 3)
                state = json.loads(state_reply.stdout) if state_reply.returncode == 0 else None
                observation.update(execution_calls=int(not state["StartedAt"].startswith("0001")) if state else None,
                                   execution_status="timeout" if attached.timeout else "policy_rejected",
                                   test_outcome="unknown", failure_stage="run", termination_reason="timeout" if attached.timeout else "policy")
                return observation
            state_command = run(["docker", "inspect", "--format", "{{json .State}}", name])
            if state_command.returncode:
                return observation
            state = json.loads(state_command.stdout)
            observation["execution_calls"] = int(not state["StartedAt"].startswith("0001"))
            if state.get("Running") or state.get("Error"):
                return observation
            exit_code = state["ExitCode"]
            observation.update(exit_code=exit_code, execution_status="completed", test_outcome="unknown",
                               failure_stage="test", termination_reason="normal")
            if state.get("OOMKilled"):
                observation.update(execution_status="oom", failure_stage="run", termination_reason="oom")
            elif exit_code >= 128:
                observation.update(signal=str(exit_code - 128), failure_stage="run", termination_reason="signal")
            try:
                cases = parse_cases(read_report(workspace), payload["test_artifact"]["kind"])
                observation.update(test_case_results=cases, tests_total=len(cases), tests_passed=sum(c["status"] == "passed" for c in cases))
                if observation["termination_reason"] == "normal":
                    passed = bool(cases) and all(c["status"] == "passed" for c in cases) and exit_code == 0
                    failed = any(c["status"] in {"failed", "error"} for c in cases)
                    observation.update(test_outcome="passed" if passed else "failed" if failed else "not_run",
                                       failure_stage="none" if passed else "test")
            except (ValueError, ET.ParseError, OSError):
                observation["resource_usage"]["notes"].append("No valid, bounded per-test report was available; success was not inferred.")
            return observation
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TimeoutError):
            observation["stderr"] = log_stream("Sandbox infrastructure failed or its deadline expired; target facts may be incomplete.")
            return observation
        finally:
            probe_clean = self._cleanup(probe_name) if probe_created else True
            target_clean = self._cleanup(name) if target_created else True
            if target_created:
                observation["resource_usage"]["wall_time_ms"] = round((time.monotonic() - started) * 1000, 3)
                observation["isolation_guarantees"] = {
                    "network": "none", "root_read_only": True, "workspace_read_only": True,
                    "allowed_write_paths": list(policy["allowed_write_paths"]), "memory_mb": policy["memory_mb"],
                    "cpu_limit": policy["cpu_limit"], "max_processes": policy["max_processes"],
                    "user": "65534:65534", "capabilities": "dropped", "output_limit_bytes": OUTPUT_LIMIT,
                    "init_process": True,
                    "write_storage": "bounded tmpfs plus a private report file",
                    "container_cleanup_confirmed": target_clean and probe_clean,
                }
            if temporary is not None:
                temporary.cleanup()
            if not probe_clean or not target_clean:
                observation.update(execution_status="infrastructure_error", test_outcome="unknown",
                                   termination_reason="infrastructure", failure_stage="environment")
                observation["resource_usage"]["notes"].append("Container cleanup was not confirmed; operator reconciliation is required.")
