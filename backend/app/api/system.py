"""Readiness, queue lag, and atomic, audited dead-letter replay."""
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
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


class LiveConfigIn(BaseModel):
    ai_provider: Optional[str] = None      # "openrouter" | "groq" | "gemini"
    ai_api_key: Optional[str] = None
    supabase_url: Optional[str] = None     # e.g. https://xxx.supabase.co
    supabase_db_password: Optional[str] = None
    upstash_redis_url: Optional[str] = None  # rediss://... URL from Upstash console


class LiveConfigOut(BaseModel):
    ai_status: str = "unconfigured"
    db_status: str = "unconfigured"
    redis_status: str = "unconfigured"
    details: dict = {}

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


@router.post("/configure")
async def configure_live(payload: LiveConfigIn):
    """
    Validate user-supplied credentials for AI, Supabase, and Upstash Redis.
    Credentials are NEVER persisted — this is a one-shot validation check.
    Returns per-service status so the UI can show which services are live.
    """
    result = LiveConfigOut()
    details: dict = {}

    # ── 1. AI provider check ──────────────────────────────────────────────────
    if payload.ai_api_key and payload.ai_provider:
        provider = payload.ai_provider.lower()
        try:
            if provider == "groq":
                import httpx
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        "https://api.groq.com/openai/v1/models",
                        headers={"Authorization": f"Bearer {payload.ai_api_key}"}
                    )
                    if r.status_code == 200:
                        result.ai_status = "ok"
                        details["ai_model_count"] = len(r.json().get("data", []))
                    else:
                        result.ai_status = "invalid_key"
            elif provider == "gemini":
                import httpx
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        f"https://generativelanguage.googleapis.com/v1beta/models?key={payload.ai_api_key}"
                    )
                    result.ai_status = "ok" if r.status_code == 200 else "invalid_key"
            elif provider == "openrouter":
                import httpx
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        "https://openrouter.ai/api/v1/models",
                        headers={"Authorization": f"Bearer {payload.ai_api_key}"}
                    )
                    result.ai_status = "ok" if r.status_code == 200 else "invalid_key"
            else:
                result.ai_status = "unknown_provider"
        except Exception as e:
            result.ai_status = f"error: {type(e).__name__}"
    elif payload.ai_api_key:
        result.ai_status = "provider_not_set"

    # ── 2. Supabase / PostgreSQL check ────────────────────────────────────────
    if payload.supabase_url and payload.supabase_db_password:
        try:
            import re
            # Supabase project ref is the subdomain of the URL
            m = re.match(r"https://([a-z0-9]+)\.supabase\.co", payload.supabase_url.rstrip("/"))
            if not m:
                result.db_status = "invalid_url"
            else:
                ref = m.group(1)
                db_url = (
                    f"postgresql+asyncpg://postgres.{ref}:{payload.supabase_db_password}"
                    f"@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
                )
                from sqlalchemy.ext.asyncio import create_async_engine
                eng = create_async_engine(db_url, echo=False, pool_size=1, max_overflow=0)
                async with eng.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                await eng.dispose()
                result.db_status = "ok"
                details["supabase_ref"] = ref
        except Exception as e:
            result.db_status = f"error: {type(e).__name__}: {str(e)[:120]}"

    # ── 3. Upstash Redis check ────────────────────────────────────────────────
    if payload.upstash_redis_url:
        try:
            from redis.asyncio import Redis as AsyncRedis
            r = AsyncRedis.from_url(
                payload.upstash_redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=8,
            )
            await r.ping()
            await r.aclose()
            result.redis_status = "ok"
        except Exception as e:
            result.redis_status = f"error: {type(e).__name__}: {str(e)[:120]}"

    result.details = details
    return result


@router.post("/seed-live")
async def seed_live_data(payload: LiveConfigIn):
    """
    Seed demo data into user-supplied Supabase + Upstash Redis.
    Falls back to local demo seed if no external credentials are given.
    AI key is stored only in memory for the duration of this request.
    """
    import re
    from scripts.generate_synthetic_data import generate

    as_of = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    seeded_services: list[str] = []

    # ── Supabase seed ─────────────────────────────────────────────────────────
    if payload.supabase_url and payload.supabase_db_password:
        m = re.match(r"https://([a-z0-9]+)\.supabase\.co", payload.supabase_url.rstrip("/"))
        if not m:
            from app.core.exceptions import AppError
            raise AppError("Invalid Supabase URL format", code="invalid_supabase_url", status_code=422)
        ref = m.group(1)
        db_url = (
            f"postgresql+asyncpg://postgres.{ref}:{payload.supabase_db_password}"
            f"@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        )
        try:
            # Run migrations then seed
            from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
            from sqlalchemy.ext.asyncio import AsyncSession
            from app.db.models import Base
            eng = create_async_engine(db_url, echo=False, pool_size=2, max_overflow=2)
            async with eng.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await generate(
                customers=100, events=500, campaigns=10, seed=42, as_of=as_of,
                override_db_url=db_url
            )
            await eng.dispose()
            seeded_services.append("supabase")
        except Exception as e:
            from app.core.exceptions import AppError
            raise AppError(f"Supabase seed failed: {e}", code="supabase_seed_failed", status_code=500)

    # ── Upstash Redis seed (write demo stream entries) ────────────────────────
    if payload.upstash_redis_url:
        try:
            from redis.asyncio import Redis as AsyncRedis
            r = AsyncRedis.from_url(
                payload.upstash_redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=10,
            )
            # Write a handful of demo events to the stream so it's non-empty
            for i in range(10):
                await r.xadd(
                    "events:stream",
                    {
                        "event_id": f"live_demo_{i:04d}",
                        "customer_id": f"cust_{i:06d}",
                        "channel": ["email","sms","push"][i % 3],
                        "event_type": ["open","click","purchase"][i % 3],
                        "source": "live_config_demo",
                    },
                    maxlen=1000,
                )
            await r.aclose()
            seeded_services.append("upstash_redis")
        except Exception as e:
            from app.core.exceptions import AppError
            raise AppError(f"Upstash seed failed: {e}", code="upstash_seed_failed", status_code=500)

    # ── Local fallback ────────────────────────────────────────────────────────
    if not seeded_services:
        await generate(customers=100, events=500, campaigns=10, seed=42, as_of=as_of)
        seeded_services.append("local_demo")

    return {
        "status": "seeded",
        "seeded_services": seeded_services,
        "message": f"Demo data generated in: {', '.join(seeded_services)}",
    }

