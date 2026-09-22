"""Dead-letter queue helpers (DB-backed for durability & visibility)."""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import DLQRepo


async def move_to_dlq(
    session: AsyncSession,
    event_id: str,
    payload: dict[str, Any],
    reason: str,
    retry_count: int,
) -> None:
    repo = DLQRepo(session)
    await repo.add(event_id=event_id, payload=payload, failure_reason=reason, retry_count=retry_count)
    await session.flush()
