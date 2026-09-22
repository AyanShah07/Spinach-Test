"""Customer intelligence endpoints with structured errors."""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.domain.scoring.engagement_score import score_at
from datetime import timezone
import logging
from app.db.repositories import CustomerRepo, EventRepo, EngagementRepo

router = APIRouter(prefix="/customers", tags=["customers"])


async def get_session(request: Request):
    async with request.app.state.session_factory() as session:
        yield session


class CustomerOut(BaseModel):
    id: str
    created_at: datetime
    attributes: dict[str, Any]
    email_opt_in: bool
    sms_opt_in: bool
    whatsapp_opt_in: bool
    push_opt_in: bool
    last_active: Optional[datetime]
    has_converted: bool
    engagement_score: Optional[float] = None
    channel_breakdown: Optional[dict] = None


class EventOut(BaseModel):
    event_id: str
    channel: str
    event_type: str
    timestamp: datetime
    metadata: dict[str, Any]


@router.get("")
async def list_customers(search: str = Query("", max_length=64), limit: int = Query(20, ge=1, le=100),
                         offset: int = Query(0, ge=0), session=Depends(get_session)):
    from sqlalchemy import select
    from app.db.models import Customer
    query = select(Customer).order_by(Customer.id).limit(limit).offset(offset)
    if search:
        query = query.where(Customer.id.contains(search, autoescape=True))
    rows = (await session.execute(query)).scalars().all()
    return [{"id": r.id, "attributes": r.attributes, "last_active": r.last_active} for r in rows]


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: str, session: AsyncSession = Depends(get_session)):
    try:
        repo = CustomerRepo(session)
        eng_repo = EngagementRepo(session)
        customer = await repo.get(customer_id)
        if not customer:
            raise NotFoundError(f"Customer '{customer_id}' not found", code="customer_not_found")
        eng = await eng_repo.get(customer_id)
        return CustomerOut(
            id=customer.id,
            created_at=customer.created_at,
            attributes=customer.attributes or {},
            email_opt_in=customer.email_opt_in,
            sms_opt_in=customer.sms_opt_in,
            whatsapp_opt_in=customer.whatsapp_opt_in,
            push_opt_in=customer.push_opt_in,
            last_active=customer.last_active,
            has_converted=customer.has_converted,
            engagement_score=round(score_at(eng.score, eng.last_updated, datetime.now(timezone.utc)), 4) if eng else None,
            channel_breakdown=eng.channel_breakdown if eng else None,
        )
    except NotFoundError:
        raise
    except Exception as exc:
        logging.getLogger(__name__).exception("Customer load failed")
        raise ServiceUnavailableError("Unable to load customer", code="customer_load_error") from exc


@router.get("/{customer_id}/timeline", response_model=list[EventOut])
async def get_timeline(
    customer_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    try:
        repo = CustomerRepo(session)
        if not await repo.get(customer_id):
            raise NotFoundError(f"Customer '{customer_id}' not found", code="customer_not_found")
        event_repo = EventRepo(session)
        events = await event_repo.timeline(customer_id, limit=limit, offset=offset)
        return [
            EventOut(
                event_id=e.event_id,
                channel=e.channel,
                event_type=e.event_type,
                timestamp=e.timestamp,
                metadata=e.metadata_ or {},
            )
            for e in events
        ]
    except NotFoundError:
        raise
    except Exception as exc:
        logging.getLogger(__name__).exception("Timeline load failed")
        raise ServiceUnavailableError("Unable to load timeline", code="timeline_error") from exc
