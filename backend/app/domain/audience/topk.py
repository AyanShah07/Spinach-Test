"""
Top-K selection via min-heap — O(M log K) time, O(K) space.

=============================================================================
ASSESSMENT NOTES — Performance & algorithmic alternative
=============================================================================

PROBLEM
  After filtering we have M candidate customers. We need the K highest
  by engagement score. A full sort is O(M log M) and materialises the
  entire list in memory.

CHOSEN APPROACH
  Stream candidates through a binary min-heap of fixed size K
  (Python heapq). When a better candidate arrives we pushpop the current
  smallest. At the end the heap holds exactly the K largest.

  Complexity:
    Time  : O(M log K)   — each of M items does at most one log-K heap op
    Space : O(K)         — heap only; candidates can be a generator

ALTERNATIVE considered: full sort then slice
  sorted(candidates, key=score, reverse=True)[:K]
  → O(M log M) time, O(M) space. Simpler code, but measurably slower and
    more memory for large M (e.g. M=200k, K=500). Rejected for the
    scale targets implied by the assignment.

ALTERNATIVE for extreme scale: approximate top-K (Count-Min / Space-Saving)
  or a pre-materialised ranking table updated by the worker. Out of scope;
  the exact heap is correct and already sub-linear in the sort cost.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(order=True)
class ScoredCustomer:
    """The root is the lowest retained score; IDs break ties deterministically."""
    score: float
    customer_id: str
    attributes: dict[str, Any] = field(compare=False, default_factory=dict)


def select_top_k(
    candidates: Iterable[tuple[str, float, dict[str, Any]]],
    k: int,
) -> list[ScoredCustomer]:
    """
    Stream candidates and keep only the top-K by score.

    Accepts any iterable (including a generator) so the caller can avoid
    materialising the full filtered set if desired.
    """
    if k <= 0:
        return []

    heap: list[ScoredCustomer] = []
    for customer_id, score, attributes in candidates:
        entry = ScoredCustomer(
            customer_id=customer_id,
            score=score,
            attributes=attributes or {},
        )
        if len(heap) < k:
            heapq.heappush(heap, entry)
        elif entry > heap[0]:
            # Better than current worst → replace
            heapq.heappushpop(heap, entry)

    # Highest score first for the API response
    return sorted(heap, key=lambda x: (x.score, x.customer_id), reverse=True)
