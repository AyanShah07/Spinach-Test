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
    # Confidence is computed from data support, not a static constant.
    from app.ai.confidence import compute_confidence
    assert resp.confidence == compute_confidence(ctx)


def test_confidence_varies_with_random_demo_data():
    """Different random campaigns must produce different confidences —
    the formula's inputs (metric coverage, audience size) move with the data."""
    from app.ai.confidence import compute_confidence
    rich = {
        "audience_size": 20000,
        "metrics": {"open_rate": 0.4, "click_rate": 0.07,
                    "conversion_rate": 0.03, "unsubscribe_rate": 0.005},
    }
    thin = {
        "audience_size": 500,
        "metrics": {"open_rate": 0.1},
    }
    assert compute_confidence(rich) != compute_confidence(thin)
    assert compute_confidence(rich) > compute_confidence(thin)


def test_confidence_formula_components():
    from math import log10
    from app.ai.confidence import (
        AUDIENCE_FULL_MARK, CANONICAL_METRICS, SAMPLE_TARGET, compute_confidence,
    )
    # Full metric set + huge audience + full sample → 1.0
    full = {
        "audience_size": AUDIENCE_FULL_MARK * 10,
        "metrics": {name: 0.1 for name in CANONICAL_METRICS},
        "engagement_score_sample": {"count": SAMPLE_TARGET},
    }
    assert compute_confidence(full) == 1.0

    # Audience reliability is log-scaled to AUDIENCE_FULL_MARK; with no metrics
    # and no sample, weights renormalize to 0.5:0.3 → audience contributes 0.3/0.8
    from app.ai.confidence import W_AUDIENCE, W_COMPLETENESS
    ctx = {"audience_size": AUDIENCE_FULL_MARK, "metrics": {}}
    expected_audience = min(1.0, log10(1 + AUDIENCE_FULL_MARK) / log10(1 + AUDIENCE_FULL_MARK))
    assert compute_confidence(ctx) == round(
        W_AUDIENCE * expected_audience / (W_COMPLETENESS + W_AUDIENCE), 3
    )

    # Sample sufficiency caps at SAMPLE_TARGET — a 5x larger sample adds nothing
    capped = {"audience_size": AUDIENCE_FULL_MARK, "metrics": {},
              "engagement_score_sample": {"count": SAMPLE_TARGET * 5}}
    at_target = {"audience_size": AUDIENCE_FULL_MARK, "metrics": {},
                 "engagement_score_sample": {"count": SAMPLE_TARGET}}
    assert compute_confidence(capped) == compute_confidence(at_target)

    # Missing sample renormalizes weights instead of taxing a constant
    no_sample = {"audience_size": AUDIENCE_FULL_MARK, "metrics": {}}
    with_sample = {"audience_size": AUDIENCE_FULL_MARK, "metrics": {},
                   "engagement_score_sample": {"count": 50}}
    assert with_sample and compute_confidence(with_sample) > compute_confidence(no_sample)


def test_confidence_blends_model_self_report():
    from app.ai.confidence import MODEL_TRUST_WEIGHT, data_support, compute_confidence
    ctx = {"audience_size": 1000, "metrics": {"open_rate": 0.2, "click_rate": 0.03}}
    support = data_support(ctx)
    # Model statement nudges, evidence dominates
    assert compute_confidence(ctx, model_confidence=0.9) == round(
        (1 - MODEL_TRUST_WEIGHT) * support + MODEL_TRUST_WEIGHT * 0.9, 3
    )
    # Out-of-range model claims are clamped before blending
    assert compute_confidence(ctx, model_confidence=2.0) == compute_confidence(ctx, model_confidence=1.0)
    assert compute_confidence(ctx, model_confidence=-1.0) == compute_confidence(ctx, model_confidence=0.0)


async def test_analysis_service_recalibrates_llm_confidence():
    """The service replaces the model's self-reported confidence with the
    documented blend of measured data support and that self-report."""
    from app.ai.confidence import compute_confidence
    from app.ai.provider import AIResponse
    from app.ai.service import AnalysisService

    class StubProvider:
        async def generate(self, prompt, context):
            return AIResponse(facts=[], recommendations=["Increase open rate by 5%."],
                              confidence=0.99, source="llm")

    ctx = {"metrics": {"open_rate": 0.2}, "audience_size": 500}
    resp = await AnalysisService().analyze(StubProvider(), "p", ctx)
    assert resp.source == "llm"
    assert resp.confidence == compute_confidence(ctx, model_confidence=0.99)
    assert resp.confidence < 0.99


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


def test_grounding_guard_rejects_goal_form_outside_context():
    """'Increase ... to X%' states an absolute target: X must exist in context.
    The old keyword exemption ('increase' anywhere) let hallucinated targets
    like 95% through."""
    from app.ai.grounding_guard import verify_grounding
    ctx = {
        "metrics": {"open_rate": 0.15, "click_rate": 0.02},
        "audience_size": 5000,
    }
    grounded, notes = verify_grounding(
        ["Increase open rate to 95% with subject-line tests."], ctx
    )
    assert not grounded
    assert any("95" in n for n in notes)


def test_grounding_guard_rejects_unverified_absolute_figures():
    from app.ai.grounding_guard import verify_grounding
    ctx = {
        "metrics": {"open_rate": 0.15},
        "audience_size": 5000,
    }
    grounded, notes = verify_grounding(
        ["You generated $4,200 in revenue from 3,000 conversions."], ctx
    )
    assert not grounded
    assert any("4,200" in n for n in notes)
    assert any("3,000" in n for n in notes)


def test_grounding_guard_allows_context_figures_time_windows_and_small_counts():
    from app.ai.grounding_guard import verify_grounding
    ctx = {
        "metrics": {"open_rate": 0.15},
        "audience_size": 5000,
    }
    recs = [
        "Your audience of 5,000 is ready for a 7-day win-back flow.",
        "Run 3 subject-line variants and recheck within 24 hours.",
    ]
    grounded, notes = verify_grounding(recs, ctx)
    assert grounded


def test_grounding_guard_engagement_sample_numbers_are_known():
    from app.ai.grounding_guard import verify_grounding
    ctx = {
        "metrics": {},
        "audience_size": 100,
        "engagement_score_sample": {"count": 100, "mean": 0.512, "max": 0.98, "min": 0.03},
    }
    grounded, _ = verify_grounding(
        ["Mean engagement score is 0.512; the maximum observed is 0.98."], ctx
    )
    assert grounded
