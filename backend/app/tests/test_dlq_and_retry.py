"""DLQ helper + scoring edge cases (exception / boundary paths)."""
from datetime import datetime, timedelta, timezone

from app.domain.scoring.engagement_score import compute_new_score


def test_negative_complaint_clamped():
    ts = datetime.now(timezone.utc)
    score, _ = compute_new_score(0.0, None, "complaint", "email", ts)
    # complaint is -5; clamp floor -50
    assert score >= -50
    assert score < 0


def test_unknown_event_type_default_weight():
    ts = datetime.now(timezone.utc)
    score, debug = compute_new_score(0.0, None, "weird_event", "email", ts)
    assert debug["base_weight"] == 0.5
    assert score > 0


def test_large_gap_decay_near_zero():
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(days=365)
    score, debug = compute_new_score(100.0, t0, "open", "email", t1, lambda_=0.05)
    assert debug["decay_factor"] < 0.01
    assert score < 5  # mostly the new open weight
