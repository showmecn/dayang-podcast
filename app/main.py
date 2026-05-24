"""Dayang Podcast — FastAPI application.

Main entry point with lifespan management, middleware, and all routers.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import settings
from app.database import engine
from app.recommender.router import router as recommend_router
from app.models.schemas import HealthResponse

logger = logging.getLogger(__name__)


_start_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    global _start_time
    _start_time = time.monotonic()
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    yield
    # Shutdown: close DB engine
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# --- Middleware ---

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_process_time(request: Request, call_next):
    """Add X-Process-Time header to every response."""
    start = time.monotonic()
    response = await call_next(request)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
    return response


# --- Routers ---

app.include_router(recommend_router)


# --- Health check ---

@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health():
    """Health check endpoint."""
    db_ok = False
    cache_ok = False
    try:
        async with engine.connect() as conn:
            from sqlalchemy import text as sa_text
            await conn.execute(sa_text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False

    try:
        from app.cache.redis_cache import health_check as cache_health
        cache_ok = await cache_health()
    except Exception:
        cache_ok = False

    uptime = time.monotonic() - _start_time if _start_time > 0 else 0.0

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version=settings.app_version,
        db_connected=db_ok,
        cache_connected=cache_ok,
        uptime_sec=round(uptime, 1),
    )


# --- Frontend ---

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    """Serve the frontend consumer page."""
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


# --- Error handlers ---

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )
