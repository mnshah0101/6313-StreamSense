"""FastAPI application: CRUD for the review UI plus job submission for the GPU worker."""

import logging
import threading
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db as dbm
from app.config import Settings, get_settings
from app.inference import build_backend
from app.media import build_store
from app.routers import analyses, games, jobs, meta, review, status, users
from app.worker import Worker, hardware_label

log = logging.getLogger("streamsense.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.check_persistent()
        if settings.auth_mode == "off":
            log.warning("AUTH IS OFF: every request acts as an admin. Never expose this API.")
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        dbm.init_engine(settings.database_url)
        store = build_store(settings)
        backend = build_backend(settings)
        app.state.settings, app.state.store, app.state.backend = settings, store, backend
        app.state.hardware = hardware_label(settings, backend)
        stop = threading.Event()
        thread = None
        if settings.embedded_worker:
            worker = Worker(settings, backend, store)
            thread = threading.Thread(
                target=worker.run_forever, args=(stop,), daemon=True, name="streamsense-worker"
            )
            thread.start()
        yield
        stop.set()
        if thread:
            thread.join(timeout=10)

    app = FastAPI(title="StreamSense API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def token_gate(request: Request, call_next):
        token = settings.token
        if token and request.method != "OPTIONS" and request.url.path != "/health":
            import hmac

            got = request.headers.get("authorization", "")
            if not hmac.compare_digest(got.encode(), f"Bearer {token}".encode()):
                return JSONResponse(
                    {"error": {"code": "unauthorized", "message": "Missing or invalid token"}},
                    401,
                )
        return await call_next(request)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail = (
            exc.detail
            if isinstance(exc.detail, dict)
            else {"code": "error", "message": str(exc.detail)}
        )
        return JSONResponse({"error": detail, "requestId": _rid(request)}, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errs = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            {
                "error": {"code": "invalid_request", "message": "Invalid request", "fields": errs},
                "requestId": _rid(request),
            },
            422,
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error (request %s)", _rid(request))
        return JSONResponse(
            {
                "error": {"code": "internal_error", "message": "Internal error"},
                "requestId": _rid(request),
            },
            500,
        )

    for r in (
        users.router,
        status.router,
        analyses.router,
        games.router,
        jobs.router,
        review.router,
        meta.router,
    ):
        app.include_router(r)
    return app


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


app = create_app()
