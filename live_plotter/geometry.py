"""Basic 2D geometry types and helpers. All polylines are immutable tuples."""

from __future__ import annotations

import math
from collections.abc import Iterable

Point = tuple[float, float]
Polyline = tuple[Point, ...]


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def polyline_length(polyline: Polyline) -> float:
    return sum(distance(p, q) for p, q in zip(polyline, polyline[1:], strict=False))


def total_length(polylines: Iterable[Polyline]) -> float:
    return sum(polyline_length(p) for p in polylines)


def reversed_polyline(polyline: Polyline) -> Polyline:
    return tuple(reversed(polyline))
