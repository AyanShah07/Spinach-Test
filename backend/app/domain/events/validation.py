"""Synchronous event payload validation (Pydantic v2)."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class Channel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    PUSH = "push"
    WEB = "web"


class EventType(str, Enum):
    OPEN = "open"
    CLICK = "click"
    PURCHASE = "purchase"
    UNSUBSCRIBE = "unsubscribe"
    COMPLAINT = "complaint"
    SEND = "send"
    DELIVERED = "delivered"
    BOUNCE = "bounce"
    VIEW = "view"


class EventIn(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=128)
    customer_id: str = Field(..., min_length=1, max_length=64)
    channel: Channel
    event_type: EventType
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def ensure_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            # Assume UTC if naive
            from datetime import timezone
            return v.replace(tzinfo=timezone.utc)
        return v


class EventAccepted(BaseModel):
    event_id: str
    status: str = "accepted"
    message: str = "Event enqueued for processing"
