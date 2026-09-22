"""Durable outbox publisher and idempotent, crash-recoverable event consumer."""
from __future__ import annotations
import asyncio
import logging
import random
from datetime import datetime, timezone
from sqlalchemy import select, update
from app.core.config import get_settings
from app.db.models import Event, Customer, EngagementScore
from app.db.repositories import CustomerRepo, EngagementRepo
from app.domain.events.validation import EventIn
from app.domain.scoring.engagement_score import compute_new_score, update_channel_breakdown, utc
from app.queue.dlq import move_to_dlq
from app.queue.outbox import claim_unpublished, mark_published, cleanup_outbox

logger = logging.getLogger(__name__)

async def process_one_event(session, payload):
    body = EventIn.model_validate(payload)
    # Lock the event, then its customer. All writers use this order. A distinct
    # event for the same customer must wait before reading the score accumulator.
    evt = (await session.execute(select(Event).where(Event.event_id == body.event_id)
                                .with_for_update())).scalar_one_or_none()
    if evt is None:
        raise ValueError("Queue event has no durable database record")
    if evt.status in ("processed", "failed"):
        return
    # The persisted event is authoritative; queue payloads cannot alter identity.
    customer = (await session.execute(select(Customer).where(Customer.id == evt.customer_id)
                                     .with_for_update())).scalar_one()
    eng = await EngagementRepo(session).get(evt.customer_id)
    ts = utc(evt.timestamp)
    old_time = utc(eng.last_updated) if eng else None
    score, debug = compute_new_score(eng.score if eng else 0, old_time,
                                     evt.event_type, evt.channel, ts)
    breakdown = update_channel_breakdown(eng.channel_breakdown if eng else {},
                                         evt.channel, evt.event_type, debug["event_weight"])
    await EngagementRepo(session).upsert(evt.customer_id, score,
                                          max(ts, old_time) if old_time else ts, breakdown)
    customer.last_active = max(ts, utc(customer.last_active)) if customer.last_active else ts
    if evt.event_type == "purchase":
        customer.has_converted = True
    if evt.event_type in ("unsubscribe", "complaint") and evt.channel != "web":
        setattr(customer, f"{evt.channel}_opt_in", False)
    evt.status = "processed"
    evt.processed_at = datetime.now(timezone.utc)
    await session.commit()

async def reconcile_outbox(queue, session_factory):
    count = 0
    async with session_factory() as session:
        rows = await claim_unpublished(session, get_settings().OUTBOX_BATCH_SIZE)
        for row in rows:
            if row.message_id and await queue.contains(row.message_id):
                # A slow consumer is not a lost message. Refresh the recovery check.
                await mark_published(session, row.id, row.message_id)
                continue
            message_id = await queue.enqueue(row.payload["customer_id"], row.payload)
            await mark_published(session, row.id, message_id)
            count += 1
        await cleanup_outbox(session)
        await session.commit()
    return count

async def fail_event(session, payload, error, retries):
    event_id = str(payload.get("event_id", "unknown"))
    evt = (await session.execute(select(Event).where(Event.event_id == event_id)
                                .with_for_update())).scalar_one_or_none()
    if evt is not None and evt.status in ("processed", "failed"):
        return
    await move_to_dlq(session, event_id, payload, str(error), retries)
    if evt is not None:
        evt.status = "failed"
    await session.commit()

async def run_worker(queue, redis, session_factory, stop_event=None):
    settings = get_settings()
    group, consumer = settings.REDIS_CONSUMER_GROUP, settings.REDIS_CONSUMER_NAME
    stop_event = stop_event or asyncio.Event()
    heartbeat = f"workers:{group}:{consumer}"

    async def heartbeat_loop():
        while not stop_event.is_set():
            try:
                await redis.set(heartbeat, datetime.now(timezone.utc).isoformat(),
                                ex=settings.WORKER_HEARTBEAT_TTL)
            except Exception:
                logger.warning("Worker heartbeat unavailable")
            await asyncio.sleep(10)

    pulse = asyncio.create_task(heartbeat_loop())
    try:
        while not stop_event.is_set():
            try:
                # Retry group creation on connection loss or Redis restart.
                await queue.ensure_group(group)
                await reconcile_outbox(queue, session_factory)
                messages = await queue.consume(group, consumer, settings.WORKER_BATCH_SIZE,
                                                settings.WORKER_BLOCK_MS)
                for msg_id, payload in messages:
                    for attempt in range(settings.WORKER_MAX_RETRIES + 1):
                        try:
                            async with session_factory() as session:
                                await process_one_event(session, payload)
                            break
                        except Exception as exc:
                            if attempt == settings.WORKER_MAX_RETRIES:
                                async with session_factory() as session:
                                    await fail_event(session, payload, exc, attempt)
                                break
                            backoff = settings.WORKER_BASE_BACKOFF_SEC * 2 ** attempt
                            await asyncio.sleep(backoff + random.uniform(0, backoff * .3))
                    # Failure here leaves a reclaimable pending entry. Reprocessing
                    # committed events is a no-op; it never applies a score twice.
                    await queue.ack(group, msg_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker iteration failed; retrying")
                await asyncio.sleep(1)
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
        try:
            await redis.delete(heartbeat)
        except Exception:
            pass
