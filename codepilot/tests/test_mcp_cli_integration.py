import json
import sys
from pathlib import Path

from pico import FakeModelClient, cli

DEMO_SERVER = Path(__file__).parents[1] / "examples" / "mcp_server" / "git_analyzer.py"


def test_cli_explicitly_loads_configured_mcp_tools(monkeypatch, tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": {
                    "git-demo": {
                        "command": [sys.executable, str(DEMO_SERVER)],
                        "cwd": "{workspace}",
                        "read_only_tools": ["git_diff", "git_history"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    args = cli.build_arg_parser().parse_args(
        ["--cwd", str(tmp_path), "--mcp-config", str(config_path)]
    )
    monkeypatch.setattr(cli, "_build_model_client", lambda args: FakeModelClient([]))

    agent = cli.build_agent(args)
    try:
        assert "mcp.git-demo.git_diff" in agent.tools
        assert "mcp.git-demo.git_history" in agent.tools
        assert agent.tools["mcp.git-demo.git_diff"]["risky"] is False
    finally:
        agent.close()
