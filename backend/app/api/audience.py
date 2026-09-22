"""Read-only audience previews, evaluated at one score reference time."""
from datetime import datetime, timezone
import heapq
from typing import Literal
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from app.db.repositories import CustomerRepo
from app.domain.events.validation import Channel
from app.domain.audience.filters import AudienceConditions, parse_conditions
from app.domain.audience.ranking import build_reason
from app.domain.audience.topk import ScoredCustomer
from app.domain.scoring.engagement_score import score_at

router = APIRouter(prefix="/audience", tags=["audience"])

class RecommendRequest(BaseModel):
    objective: Literal["conversion", "retention", "winback", "awareness", "upsell"]
    channel: Channel
    conditions: AudienceConditions = Field(default_factory=AudienceConditions)
    audience_size: int = Field(100, ge=1, le=10000)

class RankedCustomer(BaseModel):
    customer_id: str
    score: float
    reason: str

class RecommendResponse(BaseModel):
    objective: str
    channel: str
    requested_size: int
    returned_size: int
    customers: list[RankedCustomer]
    complexity_notes: dict[str, str]
    preview: bool = True

async def get_session(request: Request):
    async with request.app.state.session_factory() as session:
        yield session

@router.post("/recommend", response_model=RecommendResponse)
async def recommend_audience(body: RecommendRequest, session=Depends(get_session)):
    now = datetime.now(timezone.utc)
    filters = parse_conditions(body.conditions)
    channel = body.channel.value
    heap = []
    async for batch in CustomerRepo(session).candidate_batches(
        channel, now, filters.get("min_last_active"), filters.get("has_converted")
    ):
        for cid, raw_score, attrs, updated in batch:
            score = score_at(raw_score, updated, now)
            if filters.get("min_score") is not None and score < filters["min_score"]:
                continue
            entry = ScoredCustomer(score=score, customer_id=cid, attributes=attrs or {})
            if len(heap) < body.audience_size:
                heapq.heappush(heap, entry)
            elif entry > heap[0]:
                heapq.heapreplace(heap, entry)
    top = sorted(heap, reverse=True)
    return RecommendResponse(objective=body.objective, channel=channel,
        requested_size=body.audience_size, returned_size=len(top),
        customers=[RankedCustomer(customer_id=e.customer_id, score=round(e.score, 4),
                    reason=build_reason(e.score, e.attributes, channel, body.objective)) for e in top],
        complexity_notes={"filter": "SQL eligibility and recent-send exclusion; inspect query plans for your data",
            "freq_cap": "Confirmed sends in the previous 24 hours; preview has no side effects",
            "top_k": "O(M log K)", "space": "O(K + batch size)"})
