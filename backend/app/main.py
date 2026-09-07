"""FastAPI application factory for the Personal Knowledge Base backend."""

import hmac
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import attachments, knowledge, lessons, llm, projects, search, stats
from app.config import get_settings
from app.db.database import get_connection, init_db
from app.providers.factory import get_llm_provider, get_stt_provider


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Personal Knowledge Base", version="0.1.0", lifespan=lifespan)

    # Single-user personal KB: permissive CORS (dev server, LAN access).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    # MVP shared-secret auth: no-op when KB_API_TOKEN is unset (local/dev
    # default), so it never breaks the "usable without config" contract.
    # /health stays open for uptime checks; CORS preflight is never a real
    # request so it must pass through untouched.
    @app.middleware("http")
    async def require_api_token(request: Request, call_next):
        settings = get_settings()
        if settings.api_token and request.method != "OPTIONS" and request.url.path != "/health":
            expected = f"Bearer {settings.api_token}"
            provided = request.headers.get("authorization", "")
            if not hmac.compare_digest(provided, expected):
                return JSONResponse({"detail": "missing or invalid token"}, status_code=401)
        return await call_next(request)

    app.include_router(projects.router)
    app.include_router(knowledge.router)
    app.include_router(attachments.router)
    app.include_router(search.router)
    app.include_router(lessons.router)
    app.include_router(llm.router)
    app.include_router(stats.router)

    app.mount("/uploads", StaticFiles(directory=str(settings.uploads_dir), check_dir=False), name="uploads")

    @app.get("/health")
    def health():
        db_ok, db_err = True, None
        try:
            conn = get_connection()
            try:
                conn.execute("SELECT 1").fetchone()
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 - health should report, not crash
            db_ok, db_err = False, str(exc)
        uploads_ok, uploads_err = True, None
        try:
            settings.uploads_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=str(settings.uploads_dir), delete=True) as fh:
                fh.write(b"ok")
        except Exception as exc:  # noqa: BLE001
            uploads_ok, uploads_err = False, str(exc)
        llm_provider = get_llm_provider()
        stt_provider = get_stt_provider()
        status = "ok" if (db_ok and uploads_ok) else "degraded"
        return {
            "status": status,
            "db": "ok" if db_ok else f"error: {db_err}",
            "uploads": "ok" if uploads_ok else f"error: {uploads_err}",
            "llm": llm_provider.name,
            "stt": stt_provider.name,
        }

    return app


app = create_app()
