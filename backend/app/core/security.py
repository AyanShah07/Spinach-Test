"""Single-workspace API-key protection. Multi-tenant RBAC requires an identity layer."""
from secrets import compare_digest
from fastapi import Header, HTTPException
from app.core.config import get_settings

async def require_api_key(x_api_key: str | None = Header(default=None)):
    expected = get_settings().API_KEY
    if expected and (not x_api_key or not compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="A valid API key is required")
