"""Portable API tests; opt into real PostgreSQL/Redis with TEST_* URLs.

PostgreSQL tests create an isolated schema per test, never truncate shared data.
Redis keys are namespaced and only that test's keys are removed.
"""
import os
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from app.core.config import get_settings
from app.db.models import Base
from app.main import create_app
from app.ai.service import AnalysisService
from app.queue.redis_streams import RedisStreamsQueue

@compiles(JSONB, "sqlite")
def jsonb_sqlite(element, compiler, **kwargs):
    return "JSON"

@pytest_asyncio.fixture
async def stack(monkeypatch):
    token = f"test_{uuid4().hex}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("API_KEY", "")
    monkeypatch.setenv("RUN_EMBEDDED_WORKER", "false")
    monkeypatch.setenv("REDIS_QUEUE_STREAM", f"{token}:events")
    monkeypatch.setenv("REDIS_CONSUMER_GROUP", token)
    monkeypatch.setenv("REDIS_CONSUMER_NAME", f"{token}:worker")
    monkeypatch.setenv("WORKER_BASE_BACKOFF_SEC", "0.01")
    monkeypatch.setenv("WORKER_BLOCK_MS", "20")
    get_settings.cache_clear()
    url = os.getenv("TEST_DATABASE_URL")
    admin = None
    if url:
        admin = create_async_engine(url)
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{token}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": token}})
    else:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    redis_url = os.getenv("TEST_REDIS_URL")
    redis = Redis.from_url(redis_url, decode_responses=True) if redis_url else FakeRedis(decode_responses=True)
    queue = RedisStreamsQueue(redis)
    app = create_app()
    app.state.session_factory = sessions
    app.state.redis = redis
    app.state.queue = queue
    app.state.llm = None
    app.state.ai_service = AnalysisService()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, raise_app_exceptions=False,
                                 client=(token, 123)), base_url="http://test") as client:
        yield SimpleNamespace(app=app, client=client, sessions=sessions, redis=redis,
                              queue=queue, token=token, postgres=bool(url))
    keys = [key async for key in redis.scan_iter(match=f"*{token}*")]
    if keys:
        await redis.delete(*keys)
    await redis.aclose()
    await engine.dispose()
    if admin:
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{token}" CASCADE'))
        await admin.dispose()
    get_settings.cache_clear()
