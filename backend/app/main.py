"""
MarTech Intelligence Platform — FastAPI entrypoint.

Starts the API and (for the local/docker demo) an in-process background
worker. See lifespan() for the reliability/scalability notes on that choice.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from pathlib import Path
from fastapi import FastAPI, Depends
from app.core.security import require_api_key
from app.ai.service import AnalysisService
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import ai, audience, campaigns, customers, events, system
from app.core.exceptions import register_exception_handlers
from app.core.config import get_settings
from app.db.models import Base
from app.queue.redis_streams import RedisStreamsQueue
from app.workers.event_worker import run_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def create_llm():
    settings = get_settings()
    provider = (settings.LLM_PROVIDER or "none").lower()

    if provider == "langchain" and (settings.OPENROUTER_API_KEY or settings.GROQ_API_KEY):
        from app.ai.adapters.langchain_adapter import LangChainAdapter
        return LangChainAdapter()
    if provider == "openrouter" and settings.OPENROUTER_API_KEY:
        from app.ai.adapters.openrouter_adapter import OpenRouterAdapter
        return OpenRouterAdapter()
    if provider == "groq" and settings.GROQ_API_KEY:
        from app.ai.adapters.groq_adapter import GroqAdapter
        return GroqAdapter()
    if provider == "gemini" and settings.GEMINI_API_KEY:
        from app.ai.adapters.gemini_adapter import GeminiAdapter
        return GeminiAdapter()
    if provider == "ollama":
        from app.ai.adapters.ollama_adapter import OllamaAdapter
        return OllamaAdapter()

    logger.warning("No LLM provider configured — AI endpoints will use rule-based fallback")
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open resources; optionally run the worker in this process."""
    settings = get_settings()

    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=10)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Migrations are the default. Auto-creation is an explicit development option.
    if settings.AUTO_CREATE_TABLES:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM event_outbox LIMIT 0"))

    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=10)
    queue = RedisStreamsQueue(redis)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis = redis
    app.state.queue = queue
    app.state.llm = create_llm()
    app.state.ai_service = AnalysisService()

    stop_event = asyncio.Event()
    worker_task = (asyncio.create_task(
        run_worker(queue, redis, session_factory, stop_event=stop_event)
    ) if settings.RUN_EMBEDDED_WORKER else None)
    app.state.worker_task = worker_task
    app.state.stop_event = stop_event

    logger.info("Application started (LLM provider=%s)", settings.LLM_PROVIDER)
    yield

    stop_event.set()
    if worker_task is not None:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
    await redis.aclose()
    await engine.dispose()
    logger.info("Application stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.3.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    # Explicit origin allowlist; API-key auth is required when configured.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = settings.API_PREFIX
    register_exception_handlers(app)
    app.include_router(events.router, prefix=prefix, dependencies=[Depends(require_api_key)])
    app.include_router(customers.router, prefix=prefix, dependencies=[Depends(require_api_key)])
    app.include_router(campaigns.router, prefix=prefix, dependencies=[Depends(require_api_key)])
    app.include_router(audience.router, prefix=prefix, dependencies=[Depends(require_api_key)])
    app.include_router(ai.router, prefix=prefix, dependencies=[Depends(require_api_key)])
    app.include_router(system.router, prefix=prefix)

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def root():
        index = static_dir / "index.html"
        if index.exists():
            return FileResponse(index)
        return {"service": settings.APP_NAME, "docs": "/docs", "health": f"{prefix}/system/health"}


    return app


app = create_app()
