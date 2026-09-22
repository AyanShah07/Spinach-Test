"""Top-K and ranking tests."""
from app.domain.audience.topk import select_top_k
from app.domain.audience.ranking import build_reason


def test_top_k_returns_highest():
    candidates = [
        ("c1", 1.0, {}),
        ("c2", 50.0, {}),
        ("c3", 10.0, {}),
        ("c4", 30.0, {}),
        ("c5", 5.0, {}),
    ]
    top = select_top_k(candidates, k=3)
    scores = [e.score for e in top]
    assert scores == sorted(scores, reverse=True)
    assert set(e.customer_id for e in top) == {"c2", "c4", "c3"}


def test_top_k_empty():
    assert select_top_k([], 10) == []
    assert select_top_k([("c1", 1.0, {})], 0) == []


def test_reason_string():
    r = build_reason(25.0, {"vip": True}, "email", "conversion")
    assert "very high engagement" in r
    assert "email" in r
