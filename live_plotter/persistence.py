"""Save the ink canvas to disk so a restart continues on the same sheet of paper.

Two files in the state directory: `ink_canvas.png` (viewable: white = ink) and
`state.json` (paper size, resolution, counters). Writes are atomic (temp file + rename)
so a power cut mid-write cannot leave a half-written canvas.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import cv2

from .config import PaperConfig
from .ink_canvas import InkCanvas

log = logging.getLogger(__name__)

_FORMAT_VERSION = 1
_CANVAS_FILE = "ink_canvas.png"
_META_FILE = "state.json"


@dataclass(frozen=True)
class SavedState:
    canvas: InkCanvas
    drawn_mm: float
    cycle: int


class StateStore:
    def __init__(self, directory: Path | str) -> None:
        self._dir = Path(directory)
        self._canvas_path = self._dir / _CANVAS_FILE
        self._meta_path = self._dir / _META_FILE

    def load(self, paper: PaperConfig, px_per_mm: float) -> SavedState | None:
        """The saved state if it exists and was made for this paper; otherwise None."""
        if not self._meta_path.exists() or not self._canvas_path.exists():
            return None
        try:
            meta = json.loads(self._meta_path.read_text())
        except (OSError, ValueError) as error:
            log.warning("ignoring unreadable state file %s: %s", self._meta_path, error)
            return None
        if not _matches(meta, paper, px_per_mm):
            log.warning("saved state in %s is for a different paper/resolution; starting fresh", self._dir)
            return None
        pixels = cv2.imread(str(self._canvas_path), cv2.IMREAD_GRAYSCALE)
        expected = InkCanvas.empty(paper, px_per_mm)
        if pixels is None or pixels.shape != expected.pixels.shape:
            log.warning("saved canvas in %s is unreadable or has the wrong size; starting fresh", self._dir)
            return None
        canvas = InkCanvas(pixels, px_per_mm, expected.origin_mm)
        return SavedState(canvas=canvas, drawn_mm=float(meta.get("drawn_mm", 0.0)), cycle=int(meta.get("cycle", 0)))

    def save(self, state: SavedState) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        canvas = state.canvas
        paper_w = canvas.width / canvas.px_per_mm + 2 * canvas.origin_mm[0]
        paper_h = canvas.height / canvas.px_per_mm + 2 * canvas.origin_mm[1]
        meta = {
            "version": _FORMAT_VERSION,
            "paper": {"width_mm": paper_w, "height_mm": paper_h, "margin_mm": canvas.origin_mm[0]},
            "canvas_shape": list(canvas.pixels.shape),
            "px_per_mm": canvas.px_per_mm,
            "drawn_mm": state.drawn_mm,
            "cycle": state.cycle,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        _write_atomically(self._canvas_path, lambda tmp: cv2.imwrite(str(tmp), canvas.pixels))
        _write_atomically(self._meta_path, lambda tmp: tmp.write_text(json.dumps(meta, indent=2)))

    def clear(self) -> None:
        for path in (self._canvas_path, self._meta_path):
            path.unlink(missing_ok=True)


def _matches(meta: dict, paper: PaperConfig, px_per_mm: float) -> bool:
    saved_paper = meta.get("paper", {})
    expected = InkCanvas.empty(paper, px_per_mm)
    return (
        meta.get("version") == _FORMAT_VERSION
        and _close(saved_paper.get("width_mm"), paper.width_mm)
        and _close(saved_paper.get("height_mm"), paper.height_mm)
        and _close(saved_paper.get("margin_mm"), paper.margin_mm)
        and _close(meta.get("px_per_mm"), px_per_mm)
        and list(meta.get("canvas_shape", [])) == list(expected.pixels.shape)
    )


def _close(value: object, expected: float) -> bool:
    return isinstance(value, (int, float)) and abs(float(value) - expected) < 1e-6


def _write_atomically(path: Path, write) -> None:
    tmp = path.with_name(f"{path.stem}.tmp{path.suffix}")  # keep the extension so cv2 picks the PNG writer
    result = write(tmp)
    if result is False:  # cv2.imwrite reports failure by returning False
        tmp.unlink(missing_ok=True)
        raise OSError(f"could not write {path}")
    os.replace(tmp, path)
