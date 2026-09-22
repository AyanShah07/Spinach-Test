"""Readiness, queue lag, and atomic, audited dead-letter replay."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select, func, text
from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ConflictError, ServiceUnavailableError
from app.core.security import require_api_key
from app.db.models import DLQEvent, EventOutbox, Event
from app.db.repositories import DLQRepo
from app.queue.outbox import enqueue_outbox
from app.domain.events.validation import EventIn

router = APIRouter(prefix="/system", tags=["system"])

async def get_session(request: Request):
    async with request.app.state.session_factory() as session:
        yield session

@router.get("/live")
async def live():
    return {"status": "ok"}

@router.get("/health")
async def health(request: Request, response: Response):
    settings = get_settings()
    result = dict(status="ok", database="error", redis="error", worker="error",
                  queue_depth=None, queue_pending=None, outbox_pending=None, dlq_size=None, version="0.3.0")
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
            result["outbox_pending"] = (await session.execute(select(func.count()).select_from(EventOutbox)
                .where(EventOutbox.published_at.is_(None)))).scalar_one()
            result["dlq_size"] = (await session.execute(select(func.count()).select_from(DLQEvent)
                .where(DLQEvent.replayed_at.is_(None)))).scalar_one()
            result["database"] = "ok"
    except Exception:
        pass
    try:
        redis = request.app.state.redis
        await redis.ping()
        result["redis"] = "ok"
        async for key in redis.scan_iter(match=f"workers:{settings.REDIS_CONSUMER_GROUP}:*"):
            if await redis.exists(key):
                result["worker"] = "ok"
                break
        task = getattr(request.app.state, "worker_task", None)
        if settings.RUN_EMBEDDED_WORKER and (task is None or task.done()):
            result["worker"] = "error"
        groups = await redis.xinfo_groups(settings.REDIS_QUEUE_STREAM)
        for group in groups:
            if group.get("name") == settings.REDIS_CONSUMER_GROUP:
                result["queue_depth"] = group.get("lag")
                if result["queue_depth"] is None:
                    # Redis 6 lacks group lag; ACKed entries are deleted in this single-group stream.
                    result["queue_depth"] = max(0, await redis.xlen(settings.REDIS_QUEUE_STREAM) - group.get("pending", 0))
                result["queue_pending"] = group.get("pending", 0)
    except Exception:
        # Redis may be connected before the group exists; readiness still checks worker.
        pass
    if any(result[key] != "ok" for key in ("database", "redis", "worker")):
        result["status"] = "degraded"
        response.status_code = 503
    return result

@router.get("/dlq", dependencies=[Depends(require_api_key)])
async def list_dlq(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   session=Depends(get_session)):
    rows = await DLQRepo(session).list(limit, offset)
    return [{"id": r.id, "event_id": r.event_id, "failure_reason": r.failure_reason,
             "retry_count": r.retry_count, "failed_at": r.failed_at, "replayed_at": r.replayed_at,
             "payload": r.payload} for r in rows]

@router.post("/dlq/{dlq_id}/replay", dependencies=[Depends(require_api_key)])
async def replay_dlq(dlq_id: int, session=Depends(get_session)):
    # Match worker lock order: event first, DLQ second. An unlocked first read
    # discovers the immutable event identity without taking an inverse lock.
    row = (await session.execute(select(DLQEvent).where(DLQEvent.id == dlq_id))).scalar_one_or_none()
    if row is None:
        raise NotFoundError("DLQ entry not found", code="dlq_not_found")
    event = (await session.execute(select(Event).where(Event.event_id == row.event_id)
                                  .with_for_update())).scalar_one_or_none()
    row = (await session.execute(select(DLQEvent).where(DLQEvent.id == dlq_id)
              .with_for_update().execution_options(populate_existing=True))).scalar_one()
    if row.replayed_at:
        return {"status": "already_requeued", "event_id": row.event_id, "dlq_id": dlq_id}
    if event is None or event.status != "failed":
        raise ConflictError("Only failed durable events can be replayed", code="event_not_replayable")
    payload = EventIn(event_id=event.event_id, customer_id=event.customer_id, channel=event.channel,
                      event_type=event.event_type, timestamp=event.timestamp, metadata=event.metadata_).model_dump(mode="json")
    event.status = "pending"
    event.processed_at = None
    row.replayed_at = datetime.now(timezone.utc)
    await enqueue_outbox(session, event.event_id, payload)
    await session.commit()
    return {"status": "requeued", "event_id": row.event_id, "dlq_id": dlq_id}


@router.post("/seed")
async def seed_data():
    try:
        from scripts.generate_synthetic_data import generate
        as_of = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        await generate(customers=100, events=500, campaigns=10, seed=42, as_of=as_of)
        return {"status": "seeded", "message": "Demo campaigns, customers, and events generated successfully"}
    except Exception as exc:
        from app.core.exceptions import AppError
        raise AppError(f"Seeding failed: {exc}", code="seed_failed", status_code=500) from exc
