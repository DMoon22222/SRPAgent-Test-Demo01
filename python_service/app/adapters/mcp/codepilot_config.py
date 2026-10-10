"""Generate an explicit local CodePilot stdio server configuration without secrets."""
import argparse
import json
import sys
from pathlib import Path

from app.adapters.mcp.stdio import service_url


def build_config(url):
    return {"servers": {"srp_b": {
        "command": [sys.executable, "-m", "app.adapters.mcp.stdio", "--url", service_url(url)],
        "cwd": str(Path(__file__).resolve().parents[3]), "timeout_seconds": 300, "read_only_tools": [],
    }}}


def main():
    parser = argparse.ArgumentParser(description="Generate CodePilot's explicit --mcp-config file")
    parser.add_argument("--url", type=service_url, default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=Path(".interop/codepilot-mcp.json"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8") as stream:
            json.dump(build_config(args.url), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError:
        parser.error("Output exists; choose a new --output path to preserve your configuration")
    print(output)


if __name__ == "__main__":
    main()
