"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.middleware import BodyLimit, RateLimit, RequestContext
from .api.routes_analysis import router as analysis_router
from .api.routes_auth import router as auth_router
from .api.routes_data import router as data_router
from .api.routes_system import router as system_router
from .services.audit import request_id_var
from .services.jobs import Worker
from .settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DESCRIPTION = """
ASTRAL REST API (v1). Research and evaluation software — **not qualified for
operational conjunction assessment**.

Authentication: session cookie (browser, CSRF header required on unsafe
methods) or `Authorization: Bearer <api token>`. Errors use
`{"error": {"code", "message", "request_id"}}`.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    problems = s.check_production()
    if problems:
        raise RuntimeError("; ".join(problems))
    worker = None
    if s.worker_mode == "inprocess" and s.profile != "test":
        worker = Worker()
        worker.start()
    app.state.worker = worker
    yield
    if worker:
        worker.stop()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="ASTRAL API", version=__version__, description=DESCRIPTION, lifespan=lifespan,
                  openapi_url="/api/v1/openapi.json", docs_url="/docs", redoc_url="/redoc")
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(BodyLimit)
    app.add_middleware(RateLimit)
    app.add_middleware(CORSMiddleware, allow_origins=s.allowed_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token", "Authorization", "Idempotency-Key"])
    app.add_middleware(RequestContext)

    @app.exception_handler(HTTPException)
    async def http_error(_req: Request, exc: HTTPException):
        d = exc.detail if isinstance(exc.detail, dict) else {"code": "HTTP_ERROR", "message": str(exc.detail)}
        return JSONResponse({"error": {**d, "request_id": request_id_var.get()}}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_req: Request, exc: RequestValidationError):
        errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse({"error": {"code": "VALIDATION", "message": "request validation failed", "details": errs,
                                       "request_id": request_id_var.get()}}, status_code=422)

    for r in (auth_router, data_router, analysis_router, system_router):
        app.include_router(r)

    # Serve the built frontend if present (production image). Development uses Vite's dev server.
    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = (dist / path).resolve()
            if path and dist in f.parents and f.is_file():
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
