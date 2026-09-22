"""Single consumer-group stream, with crash recovery and deletion only after ACK.

Never trim unread entries to enforce a memory limit. Monitor lag and apply
admission control instead. Published-but-pending DB outbox rows are also retried,
so loss of Redis state can be recovered within the durable event lifecycle.
"""
from __future__ import annotations
import json
from typing import Any
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from app.core.config import get_settings
from app.queue.interface import EventQueue

class RedisStreamsQueue(EventQueue):
    def __init__(self, redis: Redis, stream_key: str | None = None):
        self.redis = redis
        self.stream = stream_key or get_settings().REDIS_QUEUE_STREAM
        self.claim_cursor = "0-0"

    async def enqueue(self, customer_id: str, payload: dict[str, Any]) -> str:
        return await self.redis.xadd(self.stream, {"customer_id": customer_id, "payload": json.dumps(payload)})

    async def ensure_group(self, consumer_group: str) -> None:
        try:
            await self.redis.xgroup_create(self.stream, consumer_group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    @staticmethod
    def decode(messages):
        out = []
        for msg_id, fields in messages:
            raw = fields.get("payload") or fields.get(b"payload")
            if isinstance(raw, bytes):
                raw = raw.decode(errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
                if not isinstance(payload, dict):
                    raise ValueError("Payload must be an object")
            except (ValueError, TypeError):
                # Preserve poison messages for the normal bounded retry/DLQ path.
                payload = {"event_id": f"malformed:{msg_id}", "raw": raw}
            out.append((msg_id, payload))
        return out

    async def consume(self, consumer_group: str, consumer_name: str, count: int = 10,
                      block_ms: int = 5000):
        claimed = await self.redis.xautoclaim(self.stream, consumer_group, consumer_name,
                    get_settings().WORKER_CLAIM_IDLE_MS, start_id=self.claim_cursor, count=count)
        self.claim_cursor = claimed[0]
        if claimed[1]:
            return self.decode(claimed[1])
        results = await self.redis.xreadgroup(consumer_group, consumer_name,
                    {self.stream: ">"}, count=count, block=block_ms)
        return self.decode([item for _, messages in results for item in messages])

    async def contains(self, message_id: str) -> bool:
        return bool(await self.redis.xrange(self.stream, min=message_id, max=message_id, count=1))

    async def ack(self, consumer_group: str, message_id: str) -> None:
        # This stream is exclusively owned by the configured group.
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.xack(self.stream, consumer_group, message_id)
            pipe.xdel(self.stream, message_id)
            await pipe.execute()
