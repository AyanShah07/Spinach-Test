"""Idempotency helper tests (unit-level; Redis integration is covered in e2e)."""
import pytest
from unittest.mock import AsyncMock

from app.domain.events.idempotency import is_duplicate, mark_seen


@pytest.mark.asyncio
async def test_is_duplicate_true():
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=True)
    assert await is_duplicate(redis, "e1") is True


@pytest.mark.asyncio
async def test_is_duplicate_false():
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=False)
    assert await is_duplicate(redis, "e1") is False
