"""Application entrypoint for the Task 4 backend scaffold.

The app exposes customer/document/task APIs plus a workbench dataset endpoint
whose response shape is intentionally aligned with the current frontend demo.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from app.api.routes.auth import router as auth_router
from app.api.routes.applications import router as application_router
from app.api.routes.business_skills import router as business_skill_router
from app.api.routes.customers import router as customer_router
from app.api.routes.extraction_skills import router as extraction_skill_router
from app.api.routes.health import router as health_router
from app.api.routes.schema_templates import router as schema_template_router
from app.api.routes.skills import router as skill_router
from app.api.routes.skill_prototypes import router as skill_prototype_router
from app.api.routes.storage import router as storage_router
from app.api.routes.system import router as system_router
from app.api.routes.tasks import router as task_router
from app.api.routes.workbench import router as workbench_router
from app.core.config import get_settings
from app.db.session import check_database_connection, dispose_engine

settings = get_settings()
DEBUG_MODE = os.environ.get("BACKEND_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}


def _configure_runtime_logging() -> None:
    log_file = settings.runtime_data_dir / "logs" / "backend.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    logger_targets = [logging.getLogger(), logging.getLogger("app"), logging.getLogger("uvicorn.error")]

    for target in logger_targets:
        if any(
            isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == str(log_file)
            for handler in target.handlers
        ):
            continue
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        target.addHandler(file_handler)

    root_logger = logging.getLogger()
    if root_logger.level == logging.NOTSET or root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)


def _sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in {"authorization", "cookie", "set-cookie", "x-api-key"}:
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


def _build_request_debug_payload(request: Request) -> dict[str, object]:
    return {
        "method": request.method,
        "path": request.url.path,
        "query": dict(request.query_params),
        "client": request.client.host if request.client else None,
        "headers": _sanitize_headers(dict(request.headers)),
    }


_configure_runtime_logging()
app = FastAPI(title=settings.app_name, debug=DEBUG_MODE)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_prefix = settings.api_prefix
app.include_router(health_router, prefix=api_prefix)
app.include_router(auth_router, prefix=api_prefix)
app.include_router(application_router, prefix=api_prefix)
app.include_router(business_skill_router, prefix=api_prefix)
app.include_router(extraction_skill_router, prefix=api_prefix)
app.include_router(skill_router, prefix=api_prefix)
app.include_router(skill_prototype_router, prefix=api_prefix)
app.include_router(storage_router, prefix=api_prefix)
app.include_router(system_router, prefix=api_prefix)
app.include_router(workbench_router, prefix=api_prefix)
app.include_router(schema_template_router, prefix=api_prefix)
app.include_router(task_router, prefix=api_prefix)
app.include_router(customer_router, prefix=api_prefix)


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    if exc.status_code >= 500:
        logging.getLogger("uvicorn.error").error(
            "[HTTPException] status=%s detail=%s request=%s",
            exc.status_code,
            exc.detail,
            _build_request_debug_payload(request),
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
    request_payload = _build_request_debug_payload(request)
    logging.getLogger("uvicorn.error").exception(
        "[UnhandledException] request=%s",
        request_payload,
    )
    detail = str(exc) if DEBUG_MODE else "Internal Server Error"
    content: dict[str, object] = {"detail": detail}
    if DEBUG_MODE:
        content["request"] = request_payload
    return JSONResponse(status_code=500, content=content)


@app.on_event("startup")
def on_startup() -> None:
    check_database_connection()


@app.on_event("shutdown")
def on_shutdown() -> None:
    dispose_engine()


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5006"))
    reload_enabled = os.environ.get("RELOAD", "false").strip().lower() in {"1", "true", "yes", "on"}
    log_level = os.environ.get("LOG_LEVEL", "debug" if DEBUG_MODE else "info").strip().lower()
    uvicorn.run("app.main:app", host=host, port=port, reload=reload_enabled, log_level=log_level)
