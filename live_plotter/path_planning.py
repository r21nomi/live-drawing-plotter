"""Choose which strokes to draw this cycle and in what order."""

from __future__ import annotations

import heapq

from .geometry import Point, Polyline, distance, polyline_length, reversed_polyline
from .ink_canvas import InkCanvas


def select_strokes(
    candidates: list[Polyline],
    canvas: InkCanvas,
    budget_mm: float,
    min_novelty: float,
    ink_radius_mm: float,
) -> list[Polyline]:
    """Greedily pick strokes that cover the most blank paper, up to a length budget.

    Score = novelty * length. Novelty is re-evaluated lazily against a scratch canvas
    that accumulates the strokes already chosen, so near-duplicates are suppressed.
    The first stroke is always allowed even if it alone exceeds the budget.
    """
    lengths = [polyline_length(c) for c in candidates]
    heap = [(-lengths[i], i) for i in range(len(candidates)) if lengths[i] > 0]
    heapq.heapify(heap)
    scratch = canvas
    selected: list[Polyline] = []
    used = 0.0
    while heap and used < budget_mm:
        _, index = heapq.heappop(heap)
        novelty = scratch.novelty(candidates[index])
        if novelty < min_novelty:
            continue
        score = novelty * lengths[index]
        if heap and score < -heap[0][0]:
            heapq.heappush(heap, (-score, index))
            continue
        if selected and used + lengths[index] > budget_mm:
            continue
        selected.append(candidates[index])
        used += lengths[index]
        scratch = scratch.with_strokes([candidates[index]], ink_radius_mm)
    return selected


def order_strokes(strokes: list[Polyline], start: Point) -> list[Polyline]:
    """Nearest-neighbour ordering, reversing strokes when their end is closer."""
    remaining = list(strokes)
    ordered: list[Polyline] = []
    current = start
    while remaining:
        best_index, best_reverse, best_distance = 0, False, float("inf")
        for index, stroke in enumerate(remaining):
            for reverse, endpoint in ((False, stroke[0]), (True, stroke[-1])):
                d = distance(current, endpoint)
                if d < best_distance:
                    best_index, best_reverse, best_distance = index, reverse, d
        chosen = remaining.pop(best_index)
        if best_reverse:
            chosen = reversed_polyline(chosen)
        ordered.append(chosen)
        current = chosen[-1]
    return ordered
