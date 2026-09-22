"""Event validation tests."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.events.validation import EventIn


def test_valid_event():
    e = EventIn(
        event_id="e1",
        customer_id="c1",
        channel="email",
        event_type="open",
        timestamp=datetime.now(timezone.utc),
        metadata={},
    )
    assert e.channel.value == "email"


def test_invalid_channel():
    with pytest.raises(ValidationError):
        EventIn(
            event_id="e1",
            customer_id="c1",
            channel="carrier_pigeon",
            event_type="open",
            timestamp=datetime.now(timezone.utc),
        )


def test_naive_timestamp_gets_utc():
    e = EventIn(
        event_id="e1",
        customer_id="c1",
        channel="sms",
        event_type="click",
        timestamp=datetime(2024, 6, 1, 12, 0, 0),  # naive
    )
    assert e.timestamp.tzinfo is not None
