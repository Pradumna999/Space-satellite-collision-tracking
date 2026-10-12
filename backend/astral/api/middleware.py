from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..services.audit import client_ip_var, request_id_var
from ..settings import get_settings

log = logging.getLogger("astral.http")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                               "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


class RequestContext(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        if not rid.isalnum() or len(rid) > 40:
            rid = uuid.uuid4().hex[:16]
        request_id_var.set(rid)
        ip = request.client.host if request.client else None
        client_ip_var.set(ip)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error request_id=%s", rid)
            response = JSONResponse({"error": {"code": "INTERNAL", "message": "internal error", "request_id": rid}}, status_code=500)
        dt = (time.perf_counter() - t0) * 1000
        response.headers["X-Request-ID"] = rid
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/docs") or request.url.path.startswith("/redoc"):
            # Swagger UI needs its CDN assets and inline script
            del response.headers["Content-Security-Policy"]
        if get_settings().cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        log.info(json.dumps({"request_id": rid, "method": request.method, "path": request.url.path, "status": response.status_code,
                             "ms": round(dt, 1), "user": getattr(request.state, "user_id", None)}))
        return response


class RateLimit(BaseHTTPMiddleware):
    """Sliding-window limit per client IP (in-process). Behind a proxy, run
    with --proxy-headers so client.host is the real address. Multi-replica
    deployments need a shared limiter (documented in SECURITY.md)."""

    def __init__(self, app):
        super().__init__(app)
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        ip = request.client.host if request.client else "?"
        bucket = "auth" if request.url.path.startswith("/api/v1/auth/login") else "all"
        limit = s.auth_rate_limit_per_minute if bucket == "auth" else s.rate_limit_per_minute
        now = time.monotonic()
        q = self.hits[(ip, bucket)]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return JSONResponse({"error": {"code": "RATE_LIMITED", "message": "too many requests"}}, status_code=429, headers={"Retry-After": "60"})
        q.append(now)
        return await call_next(request)


class BodyLimit(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        limit = get_settings().max_upload_mb * 1024 * 1024 + 64 * 1024
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > limit:
            return Response(json.dumps({"error": {"code": "PAYLOAD_TOO_LARGE", "message": f"request exceeds {get_settings().max_upload_mb} MB"}}),
                            status_code=413, media_type="application/json")
        return await call_next(request)
