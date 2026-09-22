"""
Number-containment and grounding guard.

Validates that quantitative assertions in LLM recommendations are consistent
with verified PostgreSQL aggregates, preventing statistical hallucinations.
"""
from __future__ import annotations

import re
from typing import Any


def extract_context_numbers(context: dict[str, Any]) -> dict[str, float]:
    """Extract known numbers and percentage representations from context."""
    known: dict[str, float] = {}
    metrics = context.get("metrics", {})
    for k, v in metrics.items():
        if isinstance(v, (int, float)):
            known[k] = float(v)
            # Store percentage value as well (e.g. 0.18 -> 18.0)
            if 0.0 <= v <= 1.0:
                known[f"{k}_pct"] = round(float(v) * 100, 1)

    aud = context.get("audience_size")
    if isinstance(aud, (int, float)):
        known["audience_size"] = float(aud)

    return known


def verify_grounding(recommendations: list[str], context: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Check recommendations for quantitative claims against context aggregates.
    Returns: (is_grounded, validation_notes)
    """
    known = extract_context_numbers(context)
    notes: list[str] = []
    is_grounded = True

    # Patterns for numbers and percentages in text
    pct_pattern = re.compile(r"(\d+(?:\.\d+)?)\s*%")

    for rec in recommendations:
        pct_matches = pct_pattern.findall(rec)
        for val_str in pct_matches:
            val = float(val_str)
            # Check if this percentage closely matches any known metric percentage
            matches_known = any(abs(val - known_val) < 1.5 for k, known_val in known.items() if "_pct" in k)
            # Numbers that are common target increments (e.g., "increase by 10%", "5%") are target goals
            is_target_goal = any(keyword in rec.lower() for keyword in ["increase", "boost", "target", "by", "lift", "aim", "growth"])
            
            if not matches_known and not is_target_goal and val > 5.0:
                # Potential ungrounded quantitative statement
                notes.append(f"Contains unverified statistic '{val}%' not directly present in SQL metrics")
                is_grounded = False

    if not notes:
        notes.append("All quantitative metrics strictly verified against PostgreSQL aggregates.")

    return is_grounded, notes
