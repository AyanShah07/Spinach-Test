"""Unit tests for the engagement scoring algorithm."""
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.scoring.engagement_score import (
    compute_new_score,
    BASE_WEIGHTS,
    CHANNEL_WEIGHTS,
)


def test_first_event_sets_score_to_weight():
    ts = datetime.now(timezone.utc)
    score, debug = compute_new_score(0.0, None, "purchase", "email", ts)
    expected = BASE_WEIGHTS["purchase"] * CHANNEL_WEIGHTS["email"]
    assert abs(score - expected) < 1e-6
    assert debug["event_weight"] == expected


def test_decay_reduces_old_score():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(days=14)
    # λ=0.05 → after 14 days decay ≈ e^(-0.7) ≈ 0.4966
    score, debug = compute_new_score(10.0, t0, "open", "email", t1, lambda_=0.05)
    assert score < 10.0 + 1.0  # decayed + small open weight
    assert 0.4 < debug["decay_factor"] < 0.6


def test_unsubscribe_is_negative():
    ts = datetime.now(timezone.utc)
    score, _ = compute_new_score(5.0, None, "unsubscribe", "email", ts)
    assert score < 5.0


def test_channel_multiplier_applied():
    ts = datetime.now(timezone.utc)
    s_email, _ = compute_new_score(0.0, None, "click", "email", ts)
    s_wa, _ = compute_new_score(0.0, None, "click", "whatsapp", ts)
    assert s_wa > s_email  # whatsapp multiplier 1.3 > email 1.0
