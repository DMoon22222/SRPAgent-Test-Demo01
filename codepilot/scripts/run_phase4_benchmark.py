"""Run the independent MCP / Skill Phase 4 benchmark."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pico.evaluation.phase4 import run_phase4_benchmark


def main():
    parser = argparse.ArgumentParser(description="Run CodePilot v2 Phase 4 MCP / Skill benchmark.")
    parser.add_argument("--output-root", default="benchmarks/reports", help="Directory for benchmark JSON and Markdown reports.")
    parser.add_argument("--workspace-root", default=None, help="Optional directory for fresh copied case workspaces.")
    args = parser.parse_args()
    artifact = run_phase4_benchmark(args.output_root, args.workspace_root)
    print("PHASE4_BENCHMARK_RESULT")
    print(f"BENCHMARK_CASE_COUNT={artifact['summary']['case_count']}")
    print(f"SKILL_RESULT={artifact['skill']['summary']['task_success_rate']:.2%}")
    print(f"MCP_RESULT={artifact['mcp']['summary']['task_success_rate']:.2%}")
    print(f"TOOL_GOVERNANCE_RESULT={artifact['tool_governance']['summary']['task_success_rate']:.2%}")
    print(f"INTEGRATED_RESULT={artifact['integrated']['summary']['task_success_rate']:.2%}")
    print(f"REPORT_PATH={artifact['report_paths']['final']}")


if __name__ == "__main__":
    main()
