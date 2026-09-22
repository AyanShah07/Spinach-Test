"""Per-event expiring hints. PostgreSQL UNIQUE remains authoritative."""
from redis.asyncio import Redis
from app.core.config import get_settings

async def is_duplicate(redis: Redis, event_id: str) -> bool:
    return bool(await redis.exists(f"{get_settings().REDIS_IDEMPOTENCY_SET}:{event_id}"))

async def mark_seen(redis: Redis, event_id: str, ttl_seconds: int = 86400 * 7) -> None:
    await redis.set(f"{get_settings().REDIS_IDEMPOTENCY_SET}:{event_id}", "1", ex=ttl_seconds)
