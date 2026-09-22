"""Data-access layer. Keeps SQL out of business logic."""
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import select, update, func, and_, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Customer,
    Event,
    EngagementScore,
    Campaign,
    CampaignMetric,
    DLQEvent,
)


class CustomerRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, customer_id: str) -> Optional[Customer]:
        result = await self.session.execute(select(Customer).where(Customer.id == customer_id))
        return result.scalar_one_or_none()

    async def upsert(self, customer_id: str, attributes: dict | None = None) -> Customer:
        stmt = insert(Customer).values(
            id=customer_id,
            attributes=attributes or {},
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={"attributes": attributes if attributes is not None else Customer.attributes},
        ).returning(Customer)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def candidate_batches(self, channel, now, min_last_active=None, has_converted=None):
        """Stream eligible profiles in bounded batches at one reference time.

        A recommendation is a preview. Frequency caps reflect durable processed
        send events; requesting a recommendation never consumes consent or quota.
        """
        opt_in_col = {"email": Customer.email_opt_in, "sms": Customer.sms_opt_in,
                      "whatsapp": Customer.whatsapp_opt_in, "push": Customer.push_opt_in,
                      "web": Customer.email_opt_in}[channel]
        recent_send = select(Event.id).where(
            Event.customer_id == Customer.id, Event.channel == channel,
            Event.event_type == "send", Event.status == "processed",
            Event.timestamp >= now - timedelta(hours=24), Event.timestamp <= now,
        ).exists()
        query = (select(Customer.id, func.coalesce(EngagementScore.score, 0.0),
                        Customer.attributes, EngagementScore.last_updated)
                 .outerjoin(EngagementScore, EngagementScore.customer_id == Customer.id)
                 .where(opt_in_col.is_(True), ~recent_send))
        if min_last_active is not None:
            query = query.where(Customer.last_active >= min_last_active)
        if has_converted is not None:
            query = query.where(Customer.has_converted == has_converted)
        result = await self.session.stream(query.execution_options(yield_per=1000))
        try:
            async for batch in result.partitions(1000):
                yield batch
        finally:
            await result.close()


class EventRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def exists(self, event_id: str) -> bool:
        result = await self.session.execute(
            select(Event.id).where(Event.event_id == event_id).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def insert_event(
        self,
        event_id: str,
        customer_id: str,
        channel: str,
        event_type: str,
        timestamp: datetime,
        metadata: dict,
    ) -> Event:
        evt = Event(
            event_id=event_id,
            customer_id=customer_id,
            channel=channel,
            event_type=event_type,
            timestamp=timestamp,
            metadata_=metadata,
            processed_at=datetime.now(timezone.utc),
        )
        self.session.add(evt)
        return evt

    async def timeline(self, customer_id: str, limit: int = 50, offset: int = 0) -> Sequence[Event]:
        q = (
            select(Event)
            .where(Event.customer_id == customer_id)
            .order_by(Event.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(q)
        return result.scalars().all()


class EngagementRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, customer_id: str) -> Optional[EngagementScore]:
        result = await self.session.execute(
            select(EngagementScore).where(EngagementScore.customer_id == customer_id)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        customer_id: str,
        score: float,
        last_updated: datetime,
        channel_breakdown: dict,
    ) -> EngagementScore:
        stmt = insert(EngagementScore).values(
            customer_id=customer_id,
            score=score,
            last_updated=last_updated,
            channel_breakdown=channel_breakdown,
        ).on_conflict_do_update(
            index_elements=["customer_id"],
            set_={
                "score": score,
                "last_updated": last_updated,
                "channel_breakdown": channel_breakdown,
            },
        ).returning(EngagementScore)
        result = await self.session.execute(stmt)
        return result.scalar_one()


class CampaignRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self, limit: int = 50, offset: int = 0) -> Sequence[Campaign]:
        q = select(Campaign).order_by(Campaign.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(q)
        return result.scalars().all()

    async def get(self, campaign_id: str) -> Optional[Campaign]:
        result = await self.session.execute(select(Campaign).where(Campaign.id == campaign_id))
        return result.scalar_one_or_none()

    async def metrics(self, campaign_id: str) -> Sequence[CampaignMetric]:
        result = await self.session.execute(
            select(CampaignMetric).where(CampaignMetric.campaign_id == campaign_id)
            .order_by(CampaignMetric.computed_at, CampaignMetric.id)
        )
        return result.scalars().all()


class DLQRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        event_id: str,
        payload: dict,
        failure_reason: str,
        retry_count: int,
    ) -> DLQEvent:
        row = DLQEvent(
            event_id=event_id,
            payload=payload,
            failure_reason=failure_reason,
            retry_count=retry_count,
        )
        self.session.add(row)
        return row

    async def list(self, limit: int = 100, offset: int = 0) -> Sequence[DLQEvent]:
        q = select(DLQEvent).order_by(DLQEvent.failed_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(q)
        return result.scalars().all()
