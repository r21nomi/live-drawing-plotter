"""Immutable configuration objects. Defaults target an AxiDraw V3 with A4 landscape paper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SaturationPolicy = Literal["continue", "stop", "clear"]


@dataclass(frozen=True)
class PaperConfig:
    width_mm: float = 297.0
    height_mm: float = 210.0
    margin_mm: float = 10.0

    @property
    def drawable_width_mm(self) -> float:
        return self.width_mm - 2 * self.margin_mm

    @property
    def drawable_height_mm(self) -> float:
        return self.height_mm - 2 * self.margin_mm


@dataclass(frozen=True)
class CameraConfig:
    source: int | str = 0  # camera index or /dev/video* path; a video / still image file for testing
    width: int = 640
    height: int = 480
    mirror: bool = False
    warmup_s: float = 1.5  # discard frames while auto-exposure settles
    max_age_s: float = 5.0  # a frame older than this is treated as "no frame"
    timeout_s: float = 30.0  # no frame for this long -> exit so the service restarts


@dataclass(frozen=True)
class VectorizeConfig:
    blur_kernel: int = 5
    canny_low: int = 50
    canny_high: int = 150
    simplify_epsilon_px: float = 1.2
    min_length_mm: float = 5.0
    max_stroke_mm: float = 200.0  # longer traces are split so the budget and novelty checks stay meaningful


@dataclass(frozen=True)
class DrawingConfig:
    length_budget_mm: float = 400.0
    ink_px_per_mm: float = 2.0
    ink_radius_mm: float = 1.0
    min_novelty: float = 0.3
    saturation_threshold: float = 0.6
    saturation_policy: SaturationPolicy = "continue"
    idle_sleep_s: float = 1.0


@dataclass(frozen=True)
class AxiDrawConfig:
    model: int = 1  # 1 = AxiDraw V3 / A4
    speed_pendown: int = 25
    speed_penup: int = 75
    pen_pos_up: int = 60
    pen_pos_down: int = 30
    port: str | None = None
    dry_run_speed_mm_s: float = 80.0


@dataclass(frozen=True)
class AppConfig:
    paper: PaperConfig = field(default_factory=PaperConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    vectorize: VectorizeConfig = field(default_factory=VectorizeConfig)
    drawing: DrawingConfig = field(default_factory=DrawingConfig)
    axidraw: AxiDrawConfig = field(default_factory=AxiDrawConfig)
    dry_run: bool = False
    preview: bool | None = None  # None = auto-detect a display
    state_dir: str | None = "state"  # where the ink memory is saved; None = don't persist
    fresh_start: bool = False  # discard saved ink memory at start (new sheet of paper)
    web_port: int | None = 8080  # dashboard port; None = no dashboard
