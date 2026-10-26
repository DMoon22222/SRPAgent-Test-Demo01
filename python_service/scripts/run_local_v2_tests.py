"""Run current adapter, shared O and legacy B regressions; summarize actual JUnit XML."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as ET

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.utils import uid, utcnow
from verify_local_v2 import source_metadata


def main():
    root = Path(__file__).resolve().parents[1]
    registry = ContractRegistry()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, default=registry.root.parent)
    parser.add_argument("--legacy-python", type=Path, default=root / ".venv/Scripts/python.exe")
    parser.add_argument("--output", type=Path, default=root.parent / "docs/verification/local_v2_tests.json")
    parser.add_argument("--retry-note", default=None, help="Explain a rerun without discarding the previous measured outcome")
    args = parser.parse_args()
    local = root / ".interop/p1-tests" / uid("run")
    local.mkdir(parents=True)
    # O writes hashed artifact names below pytest paths; keep their Windows prefix short.
    temporary = Path(tempfile.mkdtemp(prefix="bp1-"))
    environments = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", RUN_REPOSITORY_DOCKER_SMOKE="0")
    for key in ("DASHSCOPE_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY"):
        environments[key] = ""
    suites = {}
    definitions = [
        ("local_adapter", Path(sys.executable), root, ["tests/test_local_v2.py", "tests/test_local_v2_samples.py"]),
        ("shared_framework", Path(sys.executable), args.framework, ["tests"]),
        ("legacy_b", args.legacy_python, root, ["tests", "--ignore=tests/test_local_v2.py", "--ignore=tests/test_local_v2_samples.py"]),
    ]
    for name, python, cwd, targets in definitions:
        print("running: " + name, flush=True)
        report = local / (name + ".xml")
        command = [str(python.resolve()), "-B", "-m", "pytest", *targets, "-q", "-p", "no:cacheprovider", "--tb=short",
                   "--basetemp", str(temporary / name[0]), "--junitxml", str(report)]
        result = subprocess.run(command, cwd=cwd, env=environments, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (local / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        counts = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
        if report.exists():
            for suite in ET.parse(report).getroot().iter("testsuite"):
                for key in counts:
                    counts[key] += int(suite.get(key, 0))
        else:
            counts["errors"] = 1
        counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
        probe = subprocess.check_output([str(python.resolve()), "-c",
            "import json,platform,importlib.metadata as m; print(json.dumps({'python':platform.python_version(),"
            "'packages':{n:m.version(n) for n in ['pytest','pydantic','jsonschema']}}))"], text=True)
        suites[name] = {**counts, "return_code": result.returncode, "environment": json.loads(probe),
                       "command": ["<suite-python>", "-B", "-m", "pytest", *targets, "-q", "-p", "no:cacheprovider", "--tb=short",
                                   "--basetemp", "<private-run-temp>", "--junitxml", "<private-junit.xml>"],
                       "junit_sha256": hashlib.sha256(report.read_bytes()).hexdigest() if report.exists() else None}
        print(json.dumps({name: counts, "return_code": result.returncode}), flush=True)
    previous_attempts = []
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        previous_attempts = previous.get("previous_attempts", []) + [{
            "verified_at": previous.get("verified_at"), "result": previous["result"],
            "source_snapshot_sha256": previous.get("source_snapshot_sha256"),
            "suites": {name: {key: suite[key] for key in ("tests", "passed", "failures", "errors", "skipped")}
                       for name, suite in previous["suites"].items()},
            "retry_note": args.retry_note,
        }]
    summary = {"verified_at": utcnow(), "result": "passed" if all(s["return_code"] == 0 for s in suites.values()) else "failed",
               "scope": "Current adapter, shared framework and legacy B tests; model credentials disabled; synthetic backends unless separately recorded",
               **source_metadata(root, registry), "host_python": platform.python_version(),
               "host_packages": {name: importlib.metadata.version(name) for name in ("pytest", "pydantic", "jsonschema")},
               "suites": suites, "previous_attempts": previous_attempts,
               "raw_records": "Private .interop/p1-tests run directory; JUnit XML and logs are not committed",
               "unverified": ["Three opt-in legacy repository Docker smoke cases; current v2 Docker verification is separate"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if summary["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
