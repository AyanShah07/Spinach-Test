"""Durable publication and recovery; PostgreSQL is the event source of truth."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update, delete, or_, and_
from app.core.config import get_settings
from app.db.models import EventOutbox, Event

async def enqueue_outbox(session, event_id, payload):
    row = EventOutbox(event_id=event_id, payload=payload)
    session.add(row)
    return row

async def claim_unpublished(session, limit=500):
    retry_before = datetime.now(timezone.utc) - timedelta(minutes=2)
    query = (select(EventOutbox).join(Event, Event.event_id == EventOutbox.event_id)
        .where(Event.status == "pending", or_(EventOutbox.published_at.is_(None),
                                               EventOutbox.published_at < retry_before))
        .order_by(EventOutbox.id).limit(limit).with_for_update(skip_locked=True, of=EventOutbox))
    return (await session.execute(query)).scalars().all()

async def mark_published(session, outbox_id, message_id):
    await session.execute(update(EventOutbox).where(EventOutbox.id == outbox_id)
                          .values(published_at=datetime.now(timezone.utc), message_id=message_id))

async def cleanup_outbox(session):
    cutoff = datetime.now(timezone.utc) - timedelta(days=get_settings().OUTBOX_RETENTION_DAYS)
    terminal = select(Event.event_id).where(Event.status.in_(["processed", "failed"]))
    await session.execute(delete(EventOutbox).where(EventOutbox.created_at < cutoff,
                                                  EventOutbox.event_id.in_(terminal)))
