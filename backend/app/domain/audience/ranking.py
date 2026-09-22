"""Reason-string generation for selected audience members."""
from typing import Any


def build_reason(
    score: float,
    attributes: dict[str, Any] | None,
    channel: str,
    objective: str,
) -> str:
    """
    Short, human-readable reason. Pure function, no I/O.
    Keeps AI and rule-based paths consistent.
    """
    parts: list[str] = []
    if score >= 20:
        parts.append("very high engagement")
    elif score >= 10:
        parts.append("high engagement")
    elif score >= 5:
        parts.append("moderate engagement")
    else:
        parts.append("emerging engagement")

    parts.append(f"on {channel}")

    attrs = attributes or {}
    if attrs.get("recent_purchase"):
        parts.append("converted recently")
    if attrs.get("vip"):
        parts.append("VIP segment")

    if objective.lower() in ("retention", "winback") and score < 5:
        parts.append("at-risk / win-back candidate")

    return ", ".join(parts)
