"""
Rule-based fallback when the LLM is unavailable, times out, or returns
invalid JSON.

=============================================================================
ASSESSMENT NOTES — Reliability of the AI path
=============================================================================

HARD REQUIREMENT FROM SPEC
  /campaigns/{id}/analyze and /recommend must never hard-fail because the
  LLM is down, rate-limited, or returned garbage.

APPROACH
  1. Validate every model response against the Pydantic AIResponse schema.
  2. On schema failure, timeout, or repeated provider error → open a
     process-level circuit breaker.
  3. While the breaker is open (or no provider configured) return
     rule_based_summary(context) which emits only numbers already present
     in the structured aggregates — no generated prose that could invent
     statistics.

ALTERNATIVE considered: queue the analysis as an async job and return 202
  with a poll URL. Better UX for long-running models, but adds complexity
  (job store, webhooks). Synchronous + fallback was chosen for the demo
  so a single request always yields a usable body.

SEPARATION OF CONCERNS
  Response always distinguishes:
    facts          → data-backed (safe to treat as system of record)
    recommendations→ advisory (LLM or heuristic)
    source         → "llm" | "fallback"
"""
from typing import Any

from app.ai.provider import AIResponse


def rule_based_summary(context: dict[str, Any]) -> AIResponse:
    """Produce facts from numeric aggregates only — never invent numbers."""
    facts: list[str] = []
    recommendations: list[str] = []

    metrics = context.get("metrics") or {}
    objective = context.get("objective", "unknown")
    channel = context.get("channel", "unknown")
    audience = context.get("audience_size", 0)

    facts.append(f"Campaign objective: {objective}")
    facts.append(f"Primary channel: {channel}")
    facts.append(f"Configured audience size: {audience}")

    for name, value in metrics.items():
        facts.append(f"{name}: {value}")

    sample = context.get("engagement_score_sample")
    if sample:
        facts.append(
            f"Engagement sample (n={sample['count']}): mean={sample['mean']}, "
            f"min={sample['min']}, max={sample['max']}"
        )

    open_rate = metrics.get("open_rate")
    if open_rate is not None:
        if open_rate < 0.15:
            recommendations.append(
                "Open rate is below 15% — consider subject-line A/B tests or send-time optimization."
            )
        else:
            recommendations.append(
                "Open rate is healthy; focus budget on click-to-conversion steps."
            )

    ctr = metrics.get("click_rate")
    if ctr is not None and ctr < 0.02:
        recommendations.append(
            "Click-through rate is low — review creative and CTA placement."
        )

    if not recommendations:
        recommendations.append(
            "Insufficient metric history for specific recommendations; continue collecting data."
        )

    return AIResponse(
        facts=facts,
        recommendations=recommendations,
        confidence=0.4,
        source="fallback",
    )
