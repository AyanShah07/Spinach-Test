"""
API contract tests that do not require live Redis/Postgres.

Validates Pydantic request models and response shapes used by the API layer.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.events.validation import EventIn, EventAccepted
from app.api.audience import RecommendRequest, RecommendResponse, RankedCustomer
from app.ai.provider import AIResponse


def test_event_accepted_shape():
    a = EventAccepted(event_id="e1")
    assert a.status == "accepted"


def test_recommend_request_bounds():
    r = RecommendRequest(objective="conversion", channel="email", audience_size=10)
    assert r.audience_size == 10
    with pytest.raises(ValidationError):
        RecommendRequest(objective="x", channel="email", audience_size=0)
    with pytest.raises(ValidationError):
        RecommendRequest(objective="x", channel="email", audience_size=50_000)


def test_ranked_customer():
    c = RankedCustomer(customer_id="c1", score=1.2, reason="high engagement")
    assert c.score == 1.2


def test_ai_response_confidence_bounds():
    AIResponse(facts=[], recommendations=[], confidence=0.0)
    AIResponse(facts=[], recommendations=[], confidence=1.0)
    with pytest.raises(ValidationError):
        AIResponse(facts=[], recommendations=[], confidence=1.5)


def test_event_in_rejects_empty_id():
    with pytest.raises(ValidationError):
        EventIn(
            event_id="",
            customer_id="c",
            channel="email",
            event_type="open",
            timestamp=datetime.now(timezone.utc),
        )
