"""A raster memory of what has already been drawn on the paper.

Coordinates are paper mm; the raster covers the drawable area (inside the margins).
InkCanvas is immutable: `with_strokes` returns a new canvas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .config import PaperConfig
from .geometry import Point, Polyline

_SAMPLE_STEP_MM = 0.5
_INK = 255


@dataclass(frozen=True)
class InkCanvas:
    pixels: np.ndarray  # uint8 (height, width); 255 = inked
    px_per_mm: float
    origin_mm: Point  # paper coordinate of pixel (0, 0)

    @classmethod
    def empty(cls, paper: PaperConfig, px_per_mm: float) -> InkCanvas:
        width = max(1, math.ceil(paper.drawable_width_mm * px_per_mm))
        height = max(1, math.ceil(paper.drawable_height_mm * px_per_mm))
        return cls(np.zeros((height, width), dtype=np.uint8), px_per_mm, (paper.margin_mm, paper.margin_mm))

    @property
    def width(self) -> int:
        return self.pixels.shape[1]

    @property
    def height(self) -> int:
        return self.pixels.shape[0]

    def _to_pixels(self, points: np.ndarray) -> np.ndarray:
        """Map an (N, 2) array of mm points to clamped integer pixel coordinates."""
        scaled = (points - np.asarray(self.origin_mm)) * self.px_per_mm
        rounded = np.rint(scaled).astype(np.int32)
        rounded[:, 0] = np.clip(rounded[:, 0], 0, self.width - 1)
        rounded[:, 1] = np.clip(rounded[:, 1], 0, self.height - 1)
        return rounded

    def novelty(self, polyline: Polyline) -> float:
        """Fraction of the polyline (sampled every 0.5 mm) that runs over blank paper."""
        samples = self._to_pixels(_sample_polyline(polyline))
        blank = self.pixels[samples[:, 1], samples[:, 0]] == 0
        return float(np.count_nonzero(blank)) / len(samples)

    def with_strokes(self, polylines: list[Polyline], radius_mm: float) -> InkCanvas:
        """Return a new canvas with the given strokes inked at the given half-width."""
        thickness = max(1, int(round(2 * radius_mm * self.px_per_mm)))
        pixels = self.pixels.copy()
        for polyline in polylines:
            if not polyline:
                continue
            points = self._to_pixels(np.asarray(polyline, dtype=np.float64)).reshape(-1, 1, 2)
            cv2.polylines(pixels, [points], False, _INK, thickness, cv2.LINE_8)
        return InkCanvas(pixels, self.px_per_mm, self.origin_mm)

    def coverage(self) -> float:
        return float(np.count_nonzero(self.pixels)) / self.pixels.size

    def cleared(self) -> InkCanvas:
        return InkCanvas(np.zeros_like(self.pixels), self.px_per_mm, self.origin_mm)


def _sample_polyline(polyline: Polyline) -> np.ndarray:
    """Points along the polyline spaced about 0.5 mm apart, as an (N, 2) float array."""
    points = np.asarray(polyline, dtype=np.float64)
    if len(points) < 2:
        return points.reshape(-1, 2)
    starts, ends = points[:-1], points[1:]
    lengths = np.linalg.norm(ends - starts, axis=1)
    pieces = []
    for start, end, length in zip(starts, ends, lengths, strict=True):
        count = max(2, int(math.ceil(length / _SAMPLE_STEP_MM)) + 1)
        t = np.linspace(0.0, 1.0, count)[:, None]
        pieces.append(start + (end - start) * t)
    return np.concatenate(pieces)
