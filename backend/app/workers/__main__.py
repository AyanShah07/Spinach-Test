"""
Standalone worker process:

  python -m app.workers

Scale horizontally: run N processes with distinct REDIS_CONSUMER_NAME.
"""
from __future__ import annotations

import asyncio
import logging
import os

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import Base
from app.queue.redis_streams import RedisStreamsQueue
from app.workers.event_worker import run_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=10)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    from sqlalchemy import text
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1 FROM event_outbox LIMIT 0"))

    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    queue = RedisStreamsQueue(redis)

    stop = asyncio.Event()
    try:
        await run_worker(queue, redis, session_factory, stop_event=stop)
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
