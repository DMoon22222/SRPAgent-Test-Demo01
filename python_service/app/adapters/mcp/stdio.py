"""Standalone stdio bridge; the HTTP service owns execution and persistent state."""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import os
from urllib.parse import urlsplit

import httpx
from mcp.server.stdio import stdio_server
from pydantic import ValidationError

from app.adapters.mcp.server import ToolAdapter, create_server
from app.config import settings
from app.contracts.v1 import ApiError, DiagnosticResult
from app.services.diagnosis_service import ServiceError

ROUTES = {"diagnose_error": "/api/v1/diagnose", "execute_and_diagnose": "/api/v1/execute-and-diagnose", "check_syntax": "/api/v1/check-syntax"}


def service_url(value):
    parsed = urlsplit(value)
    try:
        local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        local = False
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
            or (parsed.scheme == "http" and not local)):
        raise argparse.ArgumentTypeError("Use an HTTPS service origin, or HTTP on a loopback host, without credentials/path/query")
    return value.rstrip("/")


class RestBridge:
    def __init__(self, url, token="", timeout=300):
        self.client = httpx.Client(base_url=service_url(url), timeout=timeout, follow_redirects=False, trust_env=False,
                                   headers={"Authorization": "Bearer " + token} if token else {})

    def process(self, request, owner):
        try:
            with self.client.stream("POST", ROUTES[request.operation], json=request.model_dump(mode="json")) as response:
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 2097152:
                        raise ServiceError("UPSTREAM_INVALID_RESPONSE", "HTTP service response exceeds 2 MiB", 502)
                if response.status_code != 200:
                    try:
                        error = ApiError.model_validate_json(data)
                    except (ValidationError, ValueError):
                        raise ServiceError("UPSTREAM_HTTP_ERROR", "HTTP service rejected the request", response.status_code) from None
                    raise ServiceError(error.code, error.message[:4096], response.status_code, error.retryable)
                try:
                    return DiagnosticResult.model_validate_json(data)
                except (ValidationError, ValueError):
                    raise ServiceError("UPSTREAM_INVALID_RESPONSE", "HTTP service returned an invalid DiagnosticResult", 502) from None
        except httpx.TimeoutException:
            raise ServiceError("UPSTREAM_TIMEOUT", "HTTP wait timed out; work may still be running. No automatic retry was made", 504) from None
        except httpx.HTTPError:
            raise ServiceError("UPSTREAM_UNAVAILABLE", "Cannot reach the configured HTTP diagnosis service", 503, True) from None

    def close(self):
        self.client.close()


async def run(url, token, timeout):
    bridge = RestBridge(url, token, timeout)
    adapter = ToolAdapter(bridge.process, workers=settings.mcp_workers, owner_resolver=lambda context: "stdio-bridge")
    server = create_server(adapter)
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        adapter.close()
        bridge.close()


def main():
    parser = argparse.ArgumentParser(description="SRP B Agent MCP stdio-to-REST bridge")
    parser.add_argument("--url", type=service_url, default="http://127.0.0.1:8000")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 300:
        parser.error("--timeout-seconds must be 1..300")
    # Inherited environment or the existing service configuration, never command-line secrets.
    token = os.environ.get("B_AGENT_API_TOKEN", settings.interop_api_token)
    asyncio.run(run(args.url, token, args.timeout_seconds))


if __name__ == "__main__":
    main()
