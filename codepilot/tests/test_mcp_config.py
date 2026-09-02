import json

import pytest

from pico.mcp.config import load_mcp_server_configs


def write_config(tmp_path, payload):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loads_explicit_mcp_config_with_workspace_cwd(tmp_path):
    config_path = write_config(
        tmp_path,
        {
            "servers": {
                "git-demo": {
                    "command": ["python", "server.py"],
                    "cwd": "{workspace}",
                    "timeout_seconds": 15,
                    "read_only_tools": ["git_diff", "git_history"],
                }
            }
        },
    )

    servers = load_mcp_server_configs(config_path, tmp_path)

    assert len(servers) == 1
    assert servers[0].server_id == "git-demo"
    assert servers[0].config.command == ["python", "server.py"]
    assert servers[0].config.cwd == str(tmp_path.resolve())
    assert servers[0].config.timeout_seconds == 15
    assert servers[0].read_only_tools == frozenset({"git_diff", "git_history"})
    assert servers[0].workspace_cwd is True


@pytest.mark.parametrize(
    "server",
    [
        {"command": ["python"], "env": {"TOKEN": "secret"}},
        {"command": ["python"], "read_only_tools": ["git_diff", "git_diff"]},
        {"command": "python"},
    ],
)
def test_rejects_unsafe_or_invalid_server_configuration(tmp_path, server):
    config_path = write_config(tmp_path, {"servers": {"git": server}})

    with pytest.raises(ValueError):
        load_mcp_server_configs(config_path, tmp_path)
