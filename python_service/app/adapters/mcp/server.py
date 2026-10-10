from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from urllib.parse import urlsplit

import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from pydantic import ValidationError

from app.config import settings
from app.contracts.v1 import ApiError, DiagnosticRequest, DiagnosticResult
from app.services.diagnosis_service import ServiceError

HTTP_PROTOCOL_VERSIONS = ("2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28")
STDIO_PROTOCOL_VERSIONS = ("2024-11-05", *HTTP_PROTOCOL_VERSIONS)
TOOL_DESCRIPTIONS = {
    "diagnose_error": "Diagnose existing EXTERNAL execution feedback for inline Python/Java source. Returns repair guidance and a retrieval decision; does not execute source or perform retrieval.",
    "execute_and_diagnose": "Execute one Main.py/Main.java file against a fixed nonempty STDIO suite and diagnose failures. All required v1 workflow, problem, code and tests fields must be supplied.",
    "check_syntax": "Check syntax/compilation of one Main.py/Main.java file. Does not run tests and cannot establish test success.",
}
logger = logging.getLogger(__name__)


def tool_definitions():
    tools = []
    for operation, description in TOOL_DESCRIPTIONS.items():
        schema = DiagnosticRequest.model_json_schema()
        schema["properties"]["operation"] = {"type": "string", "const": operation}
        tools.append(types.Tool(
            name=operation, description=description, input_schema=schema,
            output_schema=DiagnosticResult.model_json_schema(),
            annotations=types.ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                              idempotent_hint=False, open_world_hint=True),
        ))
    return tools


class ToolAdapter:
    """Bound tool execution independently of client disconnects or cancellations."""
    def __init__(self, process, *, workers=2, owner_resolver=None):
        self.process = process
        self.owner_resolver = owner_resolver or self.http_owner
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="srp-mcp")
        self.slots = BoundedSemaphore(workers)
        self.closed = False

    @staticmethod
    def http_owner(context):
        if context.request is None or not getattr(context.request.state, "principal", None):
            raise MCPError(types.INVALID_REQUEST, "Authenticated request context required")
        return context.request.state.principal

    async def list_tools(self, context, params):
        if params and params.cursor:
            raise MCPError(types.INVALID_PARAMS, "This server has no additional tool pages")
        return types.ListToolsResult(tools=tool_definitions())

    async def call_tool(self, context, params):
        if params.name not in TOOL_DESCRIPTIONS:
            raise MCPError(types.INVALID_PARAMS, "Unknown tool")
        if params.task is not None or params.input_responses:
            raise MCPError(types.INVALID_PARAMS, "Task-augmented calls and input responses are not supported")
        arguments = params.arguments or {}
        if len(json.dumps(arguments, ensure_ascii=False).encode("utf-8")) > 1048576:
            raise MCPError(types.INVALID_PARAMS, "Tool arguments exceed 1 MiB")
        try:
            request = DiagnosticRequest.model_validate(arguments)
        except ValidationError as exc:
            raise MCPError(types.INVALID_PARAMS, "Invalid DiagnosticRequest", data={
                "fields": [list(error["loc"]) for error in exc.errors()][:32],
            }) from None
        if request.operation != params.name:
            raise MCPError(types.INVALID_PARAMS, "Operation does not match tool name")
        owner = self.owner_resolver(context)
        if self.closed or not self.slots.acquire(blocking=False):
            return self.error_result(request.workflow.requestId, "SERVICE_BUSY", "All MCP execution slots are busy", True)
        try:
            future = self.executor.submit(self._execute, request, owner)
        except RuntimeError:
            self.slots.release()
            return self.error_result(request.workflow.requestId, "SERVICE_NOT_READY", "MCP service is stopping", True)
        # A canceled HTTP/stdio wait must not release a slot while its worker still runs.
        future.add_done_callback(lambda done: self.slots.release())
        return await asyncio.shield(asyncio.wrap_future(future))

    def _execute(self, request, owner):
        try:
            result = self.process(request, owner)
            data = result.model_dump(mode="json")
            return types.CallToolResult(
                structured_content=data,
                content=[types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False))],
                is_error=result.nextAction == "FIX_ENVIRONMENT",
            )
        except ServiceError as exc:
            return self.error_result(request.workflow.requestId, exc.code, str(exc)[:4096], exc.retryable)
        except Exception:
            logger.exception("MCP tool failed for request %s", request.workflow.requestId)
            return self.error_result(request.workflow.requestId, "INTERNAL_ERROR", "Diagnosis service failed", True)

    @staticmethod
    def error_result(request_id, code, message, retryable=False):
        error = ApiError(requestId=request_id, code=code, message=message, retryable=retryable)
        # Error envelopes are not DiagnosticResult, so do not attach them to structuredContent.
        return types.CallToolResult(is_error=True, content=[types.TextContent(type="text", text=error.model_dump_json())])

    def close(self):
        self.closed = True
        self.executor.shutdown(wait=True)


def create_server(adapter):
    return Server("srp-error-analysis", version="1.0.0", on_list_tools=adapter.list_tools, on_call_tool=adapter.call_tool)


def create_http_app(server):
    public = urlsplit(settings.interop_public_url)
    hosts = ["127.0.0.1", "localhost", "[::1]", "127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1", "http://localhost", "http://[::1]", "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    if public.netloc:
        hosts.append(public.netloc)
        origins.append(f"{public.scheme}://{public.netloc}")
    return server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True,
        max_request_body_size=1048576,
        transport_security=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins),
    )


class McpEndpoint:
    async def __call__(self, scope, receive, send):
        await scope["app"].state.mcp_http_app(scope, receive, send)
