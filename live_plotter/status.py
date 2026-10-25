"""What the piece is doing right now, for the preview window and the dashboard."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class StatusInfo:
    cycle: int = 0
    candidates: int = 0
    strokes: int = 0
    coverage: float = 0.0  # 0..1
    drawn_mm: float = 0.0
    dry_run: bool = False
    saturated: bool = False

    def lines(self) -> list[str]:
        mode = "DRY RUN" if self.dry_run else "AxiDraw"
        return [
            f"{mode}  cycle {self.cycle}  candidates {self.candidates}  drawing {self.strokes}",
            f"coverage {self.coverage * 100:.1f}%  drawn {self.drawn_mm / 1000:.2f} m  [q] quit",
        ]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)
