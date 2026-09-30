"""
Strict number-containment grounding guard.

Validates that EVERY quantitative assertion in LLM recommendations is
consistent with verified PostgreSQL aggregates. Any number that cannot be
traced back to the context is a statistical hallucination and fails the
check — there is no keyword-based escape hatch.

WHAT COUNTS AS GROUNDED
  A number appearing in a recommendation is accepted only if it falls in
  one of these closed classes:

  1. CONTEXT MATCH — it matches (within tolerance) a number the system
     itself computed: a metric value, its percentage form (0.18 → 18%),
     the audience size, or an engagement-score sample statistic.
  2. SMALL DIRECTIONAL DELTA — a percentage introduced by a directional
     verb + "by" (e.g. "increase open rate by 5%") with a value of at most
     MAX_TARGET_DELTA_PCT (10). Goal-form statements ("increase ... to
     95%") are NOT exempt: the target must itself match the context.
  3. LINGUISTIC INTEGERS — plain integers 1–12 used as item/step counts
     ("top 3 actions", "A/B test 2 subject lines"), never attached to %.
  4. TIME WINDOWS — numbers followed by a time unit ("7-day win-back",
     "next 24 hours"), which are conventional windows, not statistics.

  Percentages tolerate ±1.0 percentage point (rounding); absolute numbers
  tolerate 0.5% relative error (thousand separators and currency symbols
  are normalized first). Everything stricter would reject legitimate
  rounded restatements; everything looser re-admits hallucinations.
"""
from __future__ import annotations

import re
from typing import Any

# Largest directional delta ("increase ... by X%") accepted without a
# context match. Targets beyond this must exist in the data.
MAX_TARGET_DELTA_PCT = 10.0

# Percentage-point tolerance when matching stated % against context metrics.
PCT_TOLERANCE_PP = 1.0

# Relative tolerance for absolute numbers (audience sizes, counts, amounts).
ABS_REL_TOLERANCE = 0.005

_PCT_RE = re.compile(r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*%")
_NUM_RE = re.compile(r"\$?\s*(\d[\d,]*(?:\.\d+)?)")
_DELTA_RE = re.compile(r"\bby\s+\d[\d,]*(?:\.\d+)?\s*%", re.IGNORECASE)
_TIME_UNIT_RE = re.compile(
    r"^\s*(?:-|\s)*(?:day|days|week|weeks|hour|hours|month|months|year|years"
    r"|minute|minutes|second|seconds)\b",
    re.IGNORECASE,
)
_DIRECTIONAL_VERBS = (
    "increase", "boost", "raise", "lift", "grow", "improve", "uplift",
    "gain", "reduce", "decrease", "lower", "drop", "cut", "double",
    "triple", "halve",
)


def extract_context_numbers(context: dict[str, Any]) -> dict[str, float]:
    """Collect every number the system itself computed from the database."""
    known: dict[str, float] = {}
    metrics = context.get("metrics") or {}
    for k, v in metrics.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            known[k] = float(v)
            # Store percentage form as well (e.g. 0.18 -> 18.0)
            if 0.0 <= v <= 1.0:
                known[f"{k}_pct"] = round(float(v) * 100, 4)

    aud = context.get("audience_size")
    if isinstance(aud, (int, float)) and not isinstance(aud, bool):
        known["audience_size"] = float(aud)

    sample = context.get("engagement_score_sample") or {}
    for k in ("count", "mean", "max", "min"):
        v = sample.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            known[f"engagement_sample_{k}"] = float(v)

    return known


def _within_pct(value: float, known: dict[str, float]) -> bool:
    """Percentage match: within PCT_TOLERANCE_PP of any context number."""
    return any(abs(value - kv) <= PCT_TOLERANCE_PP for kv in known.values())


def _within_abs(value: float, known: dict[str, float]) -> bool:
    """Absolute match: 0.5% relative (or 0.01 flat for sub-unit ratios)."""
    for kv in known.values():
        tol = max(0.01, ABS_REL_TOLERANCE * abs(kv))
        if abs(value - kv) <= tol:
            return True
    return False


def _has_directional_verb(text: str) -> bool:
    lowered = text.lower()
    return any(f"{verb}" in lowered for verb in _DIRECTIONAL_VERBS)


def verify_grounding(recommendations: list[str], context: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Check every number in every recommendation against the context aggregates.
    Returns: (is_grounded, validation_notes)
    """
    known = extract_context_numbers(context)
    notes: list[str] = []
    is_grounded = True

    for rec in recommendations:
        # Percent spans are matched first; plain-number scanning skips them
        # so "85%" is judged once as a percentage, not again as 85.
        pct_spans: list[tuple[int, int]] = []
        for match in _PCT_RE.finditer(rec):
            value = float(match.group(1).replace(",", ""))
            pct_spans.append(match.span(1))

            if _within_pct(value, known):
                continue
            # Bounded exemption: small directional delta ("increase ... by 5%").
            if (
                value <= MAX_TARGET_DELTA_PCT
                and _DELTA_RE.search(rec)
                and _has_directional_verb(rec)
            ):
                continue
            notes.append(
                f"Contains unverified statistic '{value}%' not directly present in SQL metrics"
            )
            is_grounded = False

        for match in _NUM_RE.finditer(rec):
            if any(start <= match.start(1) < end for start, end in pct_spans):
                continue  # already judged as a percentage
            raw = match.group(1).replace(",", "")
            value = float(raw)

            # Time-window reference ("7-day", "next 24 hours") — not a statistic.
            if _TIME_UNIT_RE.match(rec[match.end(1):]):
                continue
            # Small integers are item/step counts ("top 3 actions"), not stats.
            if raw.isdigit() and 1 <= value <= 12:
                continue

            if _within_abs(value, known):
                continue
            notes.append(
                f"Contains unverified figure '{match.group(1).strip()}' "
                f"not directly present in SQL metrics"
            )
            is_grounded = False

    if not notes:
        notes.append("All quantitative metrics strictly verified against PostgreSQL aggregates.")

    return is_grounded, notes
