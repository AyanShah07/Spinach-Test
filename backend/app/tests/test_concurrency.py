"""
Concurrency notes & lightweight tests.

True multi-worker race conditions require Redis + Postgres integration tests.
Here we document the intended guarantees and smoke-test the pure scoring function
under concurrent calls (which is safe because it is pure).
"""
import asyncio
from datetime import datetime, timezone

import pytest

from app.domain.scoring.engagement_score import compute_new_score


async def _score_once():
    ts = datetime.now(timezone.utc)
    score, _ = compute_new_score(0.0, None, "click", "email", ts)
    return score


@pytest.mark.asyncio
async def test_concurrent_pure_scoring():
    results = await asyncio.gather(*[_score_once() for _ in range(20)])
    assert all(r > 0 for r in results)
