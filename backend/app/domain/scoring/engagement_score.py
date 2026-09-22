"""O(1) event-time scoring. Late contributions decay into a monotonic clock.

The stored accumulator is not clamped: clamping each write loses information and
makes the result depend on delivery order. Clamp only the displayed/ranked value.
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Any
from app.core.config import get_settings

BASE_WEIGHTS = {"purchase": 5.0, "click": 2.0, "open": 1.0, "view": 0.8,
                "delivered": 0.3, "send": 0.1, "bounce": -1.0,
                "unsubscribe": -3.0, "complaint": -5.0}
CHANNEL_WEIGHTS = {"email": 1.0, "sms": 1.2, "whatsapp": 1.3, "push": 0.9, "web": 1.1}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def days_between(a: datetime, b: datetime) -> float:
    return abs((utc(b) - utc(a)).total_seconds()) / 86400


def score_at(score: float, last_updated: datetime | None, now: datetime) -> float:
    days = max(0.0, (utc(now) - utc(last_updated)).total_seconds() / 86400) if last_updated else 0
    value = score * math.exp(-get_settings().SCORE_DECAY_LAMBDA * days)
    return max(-50.0, min(200.0, value))


def compute_new_score(current_score: float, last_updated: datetime | None, event_type: str,
                      channel: str, event_ts: datetime, lambda_: float | None = None):
    rate = get_settings().SCORE_DECAY_LAMBDA if lambda_ is None else lambda_
    base = BASE_WEIGHTS.get(event_type.lower(), 0.5)
    chan = CHANNEL_WEIGHTS.get(channel.lower(), 1.0)
    weight = base * chan
    days = days_between(last_updated, event_ts) if last_updated else 0.0
    decay = math.exp(-rate * days)
    if last_updated is None:
        new_score = weight
    elif utc(event_ts) < utc(last_updated):
        new_score = current_score + weight * decay
    else:
        new_score = current_score * decay + weight
    return new_score, {"days_since": round(days, 4), "decay_factor": round(decay, 6),
                       "base_weight": base, "channel_weight": chan, "event_weight": weight,
                       "previous_score": current_score, "new_score": new_score}


def update_channel_breakdown(breakdown: dict[str, Any] | None, channel: str,
                             event_type: str, weight: float) -> dict[str, Any]:
    bd = dict(breakdown or {})
    entry = dict(bd.get(channel.lower(), {}))
    entry.update(count=entry.get("count", 0) + 1,
                 total_weight=round(entry.get("total_weight", 0.0) + weight, 4))
    bd[channel.lower()] = entry
    return bd
