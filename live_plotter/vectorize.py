"""Turn a camera frame into polylines in paper coordinates (mm)."""

from __future__ import annotations

import cv2
import numpy as np

from .config import PaperConfig, VectorizeConfig
from .geometry import Point, Polyline, distance, polyline_length

# 4-neighbours first so straight runs are followed before diagonals.
_NEIGHBOURS = ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def detect_edges(frame_bgr: np.ndarray, cfg: VectorizeConfig) -> np.ndarray:
    """Return a uint8 edge mask (0 or 255) of the same size as the frame."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    kernel = max(1, cfg.blur_kernel | 1)  # must be odd
    blurred = cv2.GaussianBlur(gray, (kernel, kernel), 0)
    return cv2.Canny(blurred, cfg.canny_low, cfg.canny_high)


def trace_edges(edges: np.ndarray) -> list[Polyline]:
    """Chain 8-connected edge pixels into open polylines in pixel coordinates (x, y).

    Each pixel is used once. Branches are split arbitrarily, which is fine for drawing.
    The input array is not modified.
    """
    height, width = edges.shape
    stride = width + 2
    padded = np.pad(edges > 0, 1).astype(np.uint8)
    buffer = bytearray(padded.tobytes())  # local scratch copy, 1 = still unvisited edge
    ys, xs = np.nonzero(edges)
    polylines: list[Polyline] = []
    for y, x in zip(ys.tolist(), xs.tolist(), strict=True):
        index = (y + 1) * stride + (x + 1)
        if not buffer[index]:
            continue
        buffer[index] = 0
        forward = _walk(buffer, stride, x, y)
        backward = _walk(buffer, stride, x, y)
        polylines.append(tuple(reversed(backward)) + ((float(x), float(y)),) + tuple(forward))
    return polylines


def _walk(buffer: bytearray, stride: int, x: int, y: int) -> list[Point]:
    chain: list[Point] = []
    while True:
        for dx, dy in _NEIGHBOURS:
            index = (y + dy + 1) * stride + (x + dx + 1)
            if buffer[index]:
                buffer[index] = 0
                x, y = x + dx, y + dy
                chain.append((float(x), float(y)))
                break
        else:
            return chain


def simplify(polyline: Polyline, epsilon: float) -> Polyline:
    """Douglas-Peucker simplification of an open polyline."""
    if len(polyline) < 3:
        return polyline
    points = np.asarray(polyline, dtype=np.float32).reshape(-1, 1, 2)
    approx = cv2.approxPolyDP(points, epsilon, closed=False)
    return tuple((float(p[0][0]), float(p[0][1])) for p in approx)


def pixels_to_paper(
    polylines: list[Polyline],
    frame_width: int,
    frame_height: int,
    paper: PaperConfig,
    mirror: bool,
) -> list[Polyline]:
    """Fit the frame into the drawable area (keeping aspect ratio) and map points to mm."""
    scale = min(paper.drawable_width_mm / frame_width, paper.drawable_height_mm / frame_height)
    offset_x = paper.margin_mm + (paper.drawable_width_mm - frame_width * scale) / 2
    offset_y = paper.margin_mm + (paper.drawable_height_mm - frame_height * scale) / 2
    max_x = paper.width_mm - paper.margin_mm
    max_y = paper.height_mm - paper.margin_mm

    def to_mm(point: Point) -> Point:
        px = (frame_width - 1) - point[0] if mirror else point[0]
        x = min(max(offset_x + px * scale, paper.margin_mm), max_x)
        y = min(max(offset_y + point[1] * scale, paper.margin_mm), max_y)
        return (x, y)

    return [tuple(to_mm(p) for p in polyline) for polyline in polylines]


def split_long(polylines: list[Polyline], max_length: float) -> list[Polyline]:
    """Cut polylines into pieces no longer than max_length (measured along the line)."""
    pieces: list[Polyline] = []
    for polyline in polylines:
        current: list[Point] = [polyline[0]] if polyline else []
        used = 0.0
        for previous, point in zip(polyline, polyline[1:], strict=False):
            step = distance(previous, point)
            if used + step > max_length and len(current) > 1:
                pieces.append(tuple(current))
                current, used = [previous], 0.0
            current.append(point)
            used += step
        if len(current) > 1:
            pieces.append(tuple(current))
    return pieces


def filter_short(polylines: list[Polyline], min_length: float) -> list[Polyline]:
    return [p for p in polylines if polyline_length(p) >= min_length]


def vectorize_frame(
    frame_bgr: np.ndarray,
    cfg: VectorizeConfig,
    paper: PaperConfig,
    mirror: bool,
) -> list[Polyline]:
    """Full pipeline: frame -> edge polylines in paper mm, short ones dropped."""
    edges = detect_edges(frame_bgr, cfg)
    return vectorize_edges(edges, cfg, paper, mirror)


def vectorize_edges(
    edges: np.ndarray,
    cfg: VectorizeConfig,
    paper: PaperConfig,
    mirror: bool,
) -> list[Polyline]:
    height, width = edges.shape
    traced = [simplify(p, cfg.simplify_epsilon_px) for p in trace_edges(edges)]
    on_paper = pixels_to_paper(traced, width, height, paper, mirror)
    return filter_short(split_long(on_paper, cfg.max_stroke_mm), cfg.min_length_mm)
