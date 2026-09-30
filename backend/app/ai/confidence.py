"""
Deterministic confidence scoring — computed, never constant.

Confidence is derived from the same verified aggregates that feed the
prompt. It is never a static number and never the model's self-reported
value alone. Because demo/seed data is random, every input below (metric
coverage, audience size, score-sample size) differs per campaign, so the
score moves with the data run to run.

FORMULA
-------
Three evidence components, each normalized to [0, 1]:

  data_completeness    = |metrics ∩ CANONICAL_METRICS| / |CANONICAL_METRICS|
                         how much of the standard metric set the campaign has
  audience_reliability = min(1, log10(1 + audience_size) / log10(1 + AUDIENCE_FULL_MARK))
                         log scale: 500 people ≈ 0.57, 2,000 ≈ 0.78, 10,000+ ≈ full —
                         percentages over tiny audiences are statistically weak
  sample_sufficiency   = min(1, score_sample_count / SAMPLE_TARGET)
                         only when an engagement-score sample is supplied
                         (n ≥ 100 is the classic minimum-sample rule of thumb)

Each component carries a weight (0.5 / 0.3 / 0.2). Weights are renormalized
over the components actually present — e.g. with no score sample the other
two split the mass 0.5 : 0.3 → 0.625 : 0.375 — so a missing signal lowers
confidence only through what it says about the data, not by an arbitrary
constant tax.

  data_support = Σ(weight_i × component_i) / Σ(weight_i)          → [0, 1]

LLM PATH
--------
The model's stated confidence is a poorly-calibrated self-report, so it
only nudges the measured evidence:

  confidence = (1 − MODEL_TRUST_WEIGHT) × data_support
             + MODEL_TRUST_WEIGHT × model_confidence               MODEL_TRUST_WEIGHT = 0.3

FALLBACK PATH (no model involved)

  confidence = data_support

If the model omits confidence entirely, the adapter layer substitutes 0.5
(neutral); at a 0.3 weight this shifts the blend by at most ±0.15 and the
evidence term still dominates. The result is clamped to [0, 1] and rounded
to 3 decimals.
"""
from __future__ import annotations

import math
from typing import Any

# The standard metric set this platform computes for every campaign
# (see scripts/generate_synthetic_data.py — exactly these four are seeded).
CANONICAL_METRICS: tuple[str, ...] = (
    "open_rate",
    "click_rate",
    "conversion_rate",
    "unsubscribe_rate",
)

# Audience size at which audience_reliability reaches 1.0. Log-scaled below
# it: 500 people ≈ 0.57, 2,000 ≈ 0.78, 10,000+ ≈ full marks. 10k is the bar
# where a proportion estimate carries ~1 percentage-point precision, and it
# spreads the demo generator's audience range (500–20,000) across the scale
# instead of saturating it.
AUDIENCE_FULL_MARK = 10000

# Score-sample count at which sample_sufficiency reaches 1.0.
SAMPLE_TARGET = 100

W_COMPLETENESS = 0.5
W_AUDIENCE = 0.3
W_SAMPLE = 0.2

# Share of the final blend given to the model's self-reported confidence.
MODEL_TRUST_WEIGHT = 0.3


def data_support(context: dict[str, Any]) -> float:
    """Evidence quality of the context itself, in [0, 1]."""
    metrics = context.get("metrics") or {}
    present = sum(1 for name in CANONICAL_METRICS if name in metrics)
    components: list[tuple[float, float]] = [
        (W_COMPLETENESS, present / len(CANONICAL_METRICS))
    ]

    audience = context.get("audience_size")
    if audience is not None:
        audience = max(0, audience)
        reliability = math.log10(1 + audience) / math.log10(1 + AUDIENCE_FULL_MARK)
        components.append((W_AUDIENCE, min(1.0, reliability)))

    sample = context.get("engagement_score_sample")
    if sample and sample.get("count") is not None:
        components.append(
            (W_SAMPLE, min(1.0, max(0, sample["count"]) / SAMPLE_TARGET))
        )

    total_weight = sum(w for w, _ in components)
    score = sum(w * s for w, s in components) / total_weight
    return round(min(1.0, max(0.0, score)), 3)


def compute_confidence(
    context: dict[str, Any], model_confidence: float | None = None
) -> float:
    """Final confidence. Blends measured data support with the model's
    self-report when one exists; pure data support otherwise."""
    support = data_support(context)
    if model_confidence is None:
        return support
    stated = min(1.0, max(0.0, float(model_confidence)))
    return round(
        (1 - MODEL_TRUST_WEIGHT) * support + MODEL_TRUST_WEIGHT * stated, 3
    )
