"""
main.py — ProcureIQ Agent FastAPI application entrypoint.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
import structlog

from app.api.auth_api import router as auth_router
from app.api.chat import router as chat_router
from app.api.observability import router as observability_router
from app.api.tools_api import router as tools_router
from app.config import get_settings
from app.core.embedding.factory import EmbeddingProviderFactory
from app.core.security import RateLimitMiddleware

logger = structlog.get_logger("procureiq.main")
settings = get_settings()

# ── LangSmith tracing (enable via .env) ──────────────────────────────────────
if settings.langchain_tracing_v2 and settings.langchain_api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    logger.info("langsmith_tracing_enabled", project=settings.langchain_project)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure pgvector extension and tables exist on startup; Alembic handles upgrades."""
    from app.infrastructure.database import models  # noqa: F401 - register models
    from app.infrastructure.database.session import Base, engine

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("procureiq_started", version=settings.app_version)
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(tools_router)
app.include_router(observability_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return human-readable validation summary alongside field-level errors."""
    msgs = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", []) if x != "body")
        msgs.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    return JSONResponse(
        status_code=422,
        content={
            "detail": "; ".join(msgs) or "Invalid request payload.",
            "errors": jsonable_encoder(exc.errors()),
        },
    )


@app.get("/health")
async def health():
    from app.infrastructure.database.models import Tool
    from app.infrastructure.database.session import AsyncSessionLocal

    db_status = "disconnected"
    active_tools = 0
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            res = await session.execute(
                select(func.count(Tool.id)).where(Tool.is_active == True)  # noqa: E712
            )
            active_tools = int(res.scalar() or 0)
            db_status = "connected"
    except Exception as exc:
        db_status = f"error: {exc}"

    provider = EmbeddingProviderFactory.get_provider()
    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "version": settings.app_version,
        "environment": settings.environment,
        "database": db_status,
        "active_tools": active_tools,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": provider.model_name,
        "target_dimension": settings.embedding_dimension,
        "checkpointer": "postgres" if settings.use_durable_checkpointer else "memory",
        "auth_required": settings.effective_auth_enabled,
        "rate_limit_rpm": settings.rate_limit_rpm,
    }


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "endpoints": {
            "health": "GET /health",
            "chat": "POST /api/chat",
            "list_tools": "GET /api/tools",
            "get_tool": "GET /api/tools/{name}",
            "register_tool": "POST /api/tools",
            "retrieve_tools": "POST /api/tools/retrieve",
            "upload_kb": "POST /api/kb/upload",
            "session_state": "GET /api/sessions/{id}",
            "session_history": "GET /api/sessions/{id}/history",
            "session_trace": "GET /api/sessions/{id}/trace",
            "observability": "GET /api/system/observability",
        },
    }
