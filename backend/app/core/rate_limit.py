"""Atomic sliding-window limiter. A batch consumes one unit per event."""
import time
from uuid import uuid4
from fastapi import Request
from redis.asyncio import Redis
from app.core.config import get_settings
from app.core.exceptions import RateLimitError

_SCRIPT = """
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60)
if redis.call('ZCARD', KEYS[1]) + cost > tonumber(ARGV[2]) then return 0 end
for i = 1, cost do redis.call('ZADD', KEYS[1], now, ARGV[4] .. ':' .. i) end
redis.call('EXPIRE', KEYS[1], 61)
return 1
"""

async def rate_limit_events(request: Request, redis: Redis, cost: int = 1) -> None:
    settings = get_settings()
    if cost > settings.RATE_LIMIT_EVENTS_PER_MIN:
        raise RateLimitError("Batch exceeds the event rate limit", code="rate_limited")
    client_ip = request.client.host if request.client else "unknown"
    try:
        allowed = await redis.eval(_SCRIPT, 1, f"ratelimit:events:{client_ip}",
                                   time.time(), settings.RATE_LIMIT_EVENTS_PER_MIN, cost, uuid4().hex)
    except Exception:
        # Ingestion remains durable through PostgreSQL during a Redis outage.
        return
    if not allowed:
        raise RateLimitError("Event rate limit exceeded; retry after the current minute", code="rate_limited")
