"""Typed, bounded audience filters shared with the API contract."""
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, ConfigDict, Field

class AudienceConditions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_score: float | None = Field(None, ge=-50, le=200, allow_inf_nan=False)
    max_days_inactive: int | None = Field(None, ge=0, le=3650)
    has_converted: bool | None = None


def parse_conditions(conditions):
    body = conditions if isinstance(conditions, AudienceConditions) else AudienceConditions.model_validate(conditions or {})
    result = body.model_dump(exclude_none=True)
    days = result.pop("max_days_inactive", None)
    if days is not None:
        result["min_last_active"] = datetime.now(timezone.utc) - timedelta(days=days)
    return result
