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


def test_grounding_guard_detects_hallucination():
    from app.ai.grounding_guard import verify_grounding
    ctx = {
        "metrics": {"open_rate": 0.15, "click_rate": 0.02},
        "audience_size": 5000,
    }
    # Recommendation with ungrounded statistic
    recs = ["Your open rate is 85%, which is very high."]
    grounded, notes = verify_grounding(recs, ctx)
    assert not grounded
    assert any("85.0%" in n or "85" in n for n in notes)


def test_grounding_guard_passes_grounded_numbers():
    from app.ai.grounding_guard import verify_grounding
    ctx = {
        "metrics": {"open_rate": 0.15, "click_rate": 0.02},
        "audience_size": 5000,
    }
    # Recommendation with verified context metric or target
    recs = [
        "Aim to increase open rate by 10% next week.",
        "With 15.0% current open rate, consider A/B testing subject lines.",
    ]
    grounded, notes = verify_grounding(recs, ctx)
    assert grounded
