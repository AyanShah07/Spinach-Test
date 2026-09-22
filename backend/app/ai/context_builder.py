"""Build bounded, structured context for the LLM from already-computed aggregates."""
from typing import Any


def build_campaign_context(
    campaign: dict[str, Any],
    metrics: list[dict[str, Any]],
    sample_scores: list[float] | None = None,
) -> dict[str, Any]:
    """
    Never pass raw event logs. Only aggregates already stored in the system.
    This keeps prompt size bounded and prevents the model from inventing stats.
    """
    metrics_map = {m["metric_name"]: m["value"] for m in metrics}
    ctx: dict[str, Any] = {
        "campaign_id": campaign.get("id"),
        "objective": campaign.get("objective"),
        "channel": campaign.get("channel"),
        "status": campaign.get("status"),
        "audience_size": campaign.get("audience_size", 0),
        "metrics": metrics_map,
    }
    if sample_scores:
        ctx["engagement_score_sample"] = {
            "count": len(sample_scores),
            "mean": round(sum(sample_scores) / len(sample_scores), 3) if sample_scores else 0,
            "max": round(max(sample_scores), 3) if sample_scores else 0,
            "min": round(min(sample_scores), 3) if sample_scores else 0,
        }
    return ctx
