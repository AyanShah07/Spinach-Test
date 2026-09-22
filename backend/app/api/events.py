"""
Event ingestion — single + batch.

Reliability path (principal design):
  1. Validate
  2. Ensure customer
  3. ONE DB transaction: insert event (ON CONFLICT skip) + outbox row
  4. COMMIT → 202  (durable even if Redis is down)
  5. Worker publishes outbox entries and recovers stalled pending events
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.core.rate_limit import rate_limit_events
from app.db.models import Customer, Event
from app.domain.events.validation import EventIn, EventAccepted
from app.queue.interface import EventQueue
from app.queue.outbox import enqueue_outbox

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


class BatchEventIn(BaseModel):
    events: list[EventIn] = Field(..., min_length=1, max_length=500)


class BatchEventOut(BaseModel):
    accepted: int
    duplicates: int
    rejected: list[dict[str, Any]] = Field(default_factory=list)


async def get_redis(request: Request) -> Redis:
    return request.app.state.redis


async def get_queue(request: Request) -> EventQueue:
    return request.app.state.queue


async def get_session(request: Request):
    async with request.app.state.session_factory() as session:
        yield session


async def _persist_one(
    session: AsyncSession,
    body: EventIn,
) -> str:
    """
    Insert customer + event + outbox in caller's transaction.
    Returns: "accepted" | "duplicate"
    """
    # Ensure customer exists
    await session.execute(
        insert(Customer)
        .values(id=body.customer_id, attributes={})
        .on_conflict_do_nothing(index_elements=["id"])
    )

    payload = body.model_dump(mode="json")
    stmt = (
        insert(Event)
        .values(
            event_id=body.event_id,
            customer_id=body.customer_id,
            channel=body.channel.value if hasattr(body.channel, "value") else body.channel,
            event_type=body.event_type.value if hasattr(body.event_type, "value") else body.event_type,
            timestamp=body.timestamp,
            metadata_=body.metadata or {},
            status="pending",
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(Event.id)
    )
    result = await session.execute(stmt)
    row_id = result.scalar_one_or_none()
    if row_id is None:
        return "duplicate"

    await enqueue_outbox(session, body.event_id, payload)
    return "accepted"


@router.post("", response_model=EventAccepted, status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(
    body: EventIn,
    request: Request,
    redis: Redis = Depends(get_redis),
    queue: EventQueue = Depends(get_queue),
    session: AsyncSession = Depends(get_session),
):
    await rate_limit_events(request, redis)

    try:
        outcome = await _persist_one(session, body)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("Event persistence failed")
        raise ServiceUnavailableError("Unable to persist event", code="persist_failed") from exc

    if outcome == "duplicate":
        return EventAccepted(
            event_id=body.event_id,
            status="duplicate",
            message="Event already exists in DB",
        )

    # The worker is the only publisher; 202 means event + outbox committed.
    return EventAccepted(event_id=body.event_id)


@router.post("/batch", response_model=BatchEventOut, status_code=status.HTTP_202_ACCEPTED)
async def ingest_batch(
    body: BatchEventIn,
    request: Request,
    redis: Redis = Depends(get_redis),
    queue: EventQueue = Depends(get_queue),
    session: AsyncSession = Depends(get_session),
):
    """
    Batch ingest (≤500). Per-item validation already done by Pydantic list.
    Partial success: accepted + duplicates + rejected (shouldn't happen post-validation).
    """
    await rate_limit_events(request, redis, cost=len(body.events))

    accepted = 0
    duplicates = 0
    rejected: list[dict[str, Any]] = []

    try:
        for i, evt in enumerate(body.events):
            try:
                async with session.begin_nested():
                    outcome = await _persist_one(session, evt)
                    await session.flush()
                if outcome == "accepted":
                    accepted += 1
                else:
                    duplicates += 1
            except Exception as exc:
                logger.exception("Batch item persistence failed")
                rejected.append({"index": i, "event_id": evt.event_id, "reason": "Unable to persist event"})
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("Batch persistence failed")
        raise ServiceUnavailableError("Unable to persist batch", code="batch_persist_failed") from exc

    return BatchEventOut(accepted=accepted, duplicates=duplicates, rejected=rejected)


@router.get("/{event_id}")
async def event_status(event_id: str, session: AsyncSession = Depends(get_session)):
    event = (await session.execute(select(Event).where(Event.event_id == event_id))).scalar_one_or_none()
    if event is None:
        raise NotFoundError("Event not found", code="event_not_found")
    return {"event_id": event.event_id, "status": event.status, "processed_at": event.processed_at}
