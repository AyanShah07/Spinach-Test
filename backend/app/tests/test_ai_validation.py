"""AI response validation + fallback."""
from app.ai.fallback import rule_based_summary
from app.ai.provider import AIResponse
from app.ai.validators import validate_ai_response


def test_valid_response():
    raw = {"facts": ["a"], "recommendations": ["b"], "confidence": 0.8}
    resp = validate_ai_response(raw)
    assert resp.confidence == 0.8


def test_invalid_confidence():
    import pytest
    with pytest.raises(ValueError):
        validate_ai_response({"facts": [], "recommendations": [], "confidence": 2.0})


def test_fallback_produces_facts():
    ctx = {
        "objective": "conversion",
        "channel": "email",
        "audience_size": 1000,
        "metrics": {"open_rate": 0.12, "click_rate": 0.01},
    }
    resp = rule_based_summary(ctx)
    assert resp.source == "fallback"
    assert len(resp.facts) >= 3
    assert resp.confidence <= 0.5
