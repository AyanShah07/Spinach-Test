"""Campaign list & analytics with structured errors."""
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.repositories import CampaignRepo

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


async def get_session(request: Request):
    async with request.app.state.session_factory() as session:
        yield session


class CampaignOut(BaseModel):
    id: str
    name: str
    objective: str
    channel: str
    created_at: datetime
    status: str
    audience_size: int


class MetricOut(BaseModel):
    metric_name: str
    value: float
    computed_at: datetime


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    try:
        repo = CampaignRepo(session)
        rows = await repo.list(limit=limit, offset=offset)
        return [
            CampaignOut(
                id=c.id,
                name=c.name,
                objective=c.objective,
                channel=c.channel,
                created_at=c.created_at,
                status=c.status,
                audience_size=c.audience_size,
            )
            for c in rows
        ]
    except Exception as exc:
        from app.core.exceptions import AppError
        logging.getLogger(__name__).exception("Campaign listing failed")
        raise AppError("Unable to list campaigns", code="campaign_list_error", status_code=503) from exc


@router.get("/{campaign_id}/analytics")
async def campaign_analytics(campaign_id: str, session: AsyncSession = Depends(get_session)):
    try:
        repo = CampaignRepo(session)
        campaign = await repo.get(campaign_id)
        if not campaign:
            raise NotFoundError(f"Campaign '{campaign_id}' not found", code="campaign_not_found")
        metrics = await repo.metrics(campaign_id)
        return {
            "campaign": CampaignOut(
                id=campaign.id,
                name=campaign.name,
                objective=campaign.objective,
                channel=campaign.channel,
                created_at=campaign.created_at,
                status=campaign.status,
                audience_size=campaign.audience_size,
            ),
            "metrics": [
                MetricOut(metric_name=m.metric_name, value=m.value, computed_at=m.computed_at)
                for m in metrics
            ],
        }
    except NotFoundError:
        raise
    except Exception as exc:
        from app.core.exceptions import AppError
        logging.getLogger(__name__).exception("Analytics failed")
        raise AppError("Unable to load analytics", code="analytics_error", status_code=503) from exc
