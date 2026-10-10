import hashlib
import hmac
import ipaddress

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.contracts.v1 import ApiError


def is_local(scope):
    host = scope.get("client", ("", 0))[0]
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "testclient"


class InteropBoundary:
    """Protect new interop surfaces without changing the legacy API contract."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        legacy = scope["type"] == "http" and scope["path"].startswith("/api/") and not scope["path"].startswith("/api/v1/")
        if legacy and not is_local(scope):
            response = JSONResponse(status_code=403, content=ApiError(
                code="LEGACY_LOCAL_ONLY", message="Legacy endpoints are for trusted same-host callers; use /api/v1 remotely").model_dump())
            return await response(scope, receive, send)
        protected = scope["type"] == "http" and (scope["path"].startswith("/api/v1/") or scope["path"] in {"/a2a", "/mcp", "/mcp/"})
        if not protected:
            return await self.app(scope, receive, send)
        request = Request(scope)
        token = settings.interop_api_token
        auth = request.headers.get("authorization", "")
        if token:
            if not hmac.compare_digest(auth, "Bearer " + token):
                response = JSONResponse(status_code=401, content=ApiError(code="UNAUTHORIZED", message="Valid bearer token required").model_dump(),
                                        headers={"WWW-Authenticate": "Bearer"})
                return await response(scope, receive, send)
            principal = "token:" + hashlib.sha256(token.encode()).hexdigest()
        else:
            if not is_local(scope):
                response = JSONResponse(status_code=403, content=ApiError(code="REMOTE_AUTH_REQUIRED", message="Configure INTEROP_API_TOKEN for remote access").model_dump())
                return await response(scope, receive, send)
            principal = "local-development"
        scope.setdefault("state", {})["principal"] = principal
        # Check the actual streamed body, not just an optional Content-Length header.
        chunks, length = [], 0
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            chunk = event.get("body", b"")
            length += len(chunk)
            if length > 1048576:
                response = JSONResponse(status_code=413, content=ApiError(code="REQUEST_TOO_LARGE", message="Request exceeds 1 MiB").model_dump())
                return await response(scope, receive, send)
            chunks.append(chunk)
            if not event.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
