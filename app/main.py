"""DrunkenBot cloud service: IDE license validation + training-farm auth.

Run with: uvicorn app.main:app --host 0.0.0.0 --port 8000

Put this behind a TLS-terminating reverse proxy (Caddy/nginx/Cloudflare) in
any real deployment -- this app itself speaks plain HTTP only.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.admin_ui.router import router as admin_ui_router
from app.config import get_settings
from app.download_page import router as download_router
from app.db import init_db
from app.routers import admin, auth, license

app = FastAPI(
    title="DrunkenBot Cloud Service",
    description="IDE license validation and cloud-training-farm subscription management.",
    version="0.1.0",
)

app.add_middleware(SessionMiddleware, secret_key=get_settings().session_secret_key, same_site="lax")

app.include_router(license.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin_ui_router)
app.include_router(download_router)


@app.on_event("startup")
def on_startup() -> None:
    """Ensure database tables exist before serving requests."""

    init_db()


@app.get("/")
def root() -> dict[str, str]:
    """Basic status/landing response for anyone hitting the bare host.

    Returns:
        Status payload pointing at the docs and health check.
    """

    return {
        "message": "DrunkenBot Cloud Service API is running",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health() -> dict[str, str]:
    """Basic liveness check.

    Returns:
        Status payload.
    """

    return {"status": "ok"}
