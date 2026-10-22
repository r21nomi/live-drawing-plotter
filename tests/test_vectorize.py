import cv2
import numpy as np
import pytest

from live_plotter.config import PaperConfig, VectorizeConfig
from live_plotter.vectorize import (
    detect_edges,
    filter_short,
    pixels_to_paper,
    simplify,
    split_long,
    trace_edges,
    vectorize_frame,
)


def _blank(h=60, w=80):
    return np.zeros((h, w), dtype=np.uint8)


def test_trace_single_horizontal_line():
    edges = _blank()
    edges[20, 10:51] = 255
    polylines = trace_edges(edges)
    assert len(polylines) == 1
    line = polylines[0]
    assert len(line) == 41
    assert {line[0], line[-1]} == {(10.0, 20.0), (50.0, 20.0)}


def test_trace_separates_disconnected_lines():
    edges = _blank()
    edges[10, 5:30] = 255
    edges[40, 5:30] = 255
    polylines = trace_edges(edges)
    assert len(polylines) == 2


def test_trace_follows_diagonal():
    edges = _blank()
    for i in range(20):
        edges[10 + i, 10 + i] = 255
    polylines = trace_edges(edges)
    assert len(polylines) == 1
    assert len(polylines[0]) == 20


def test_trace_empty_image():
    assert trace_edges(_blank()) == []


def test_simplify_collapses_straight_line():
    line = tuple((float(x), 5.0) for x in range(30))
    assert simplify(line, epsilon=1.0) == ((0.0, 5.0), (29.0, 5.0))


def test_simplify_keeps_short_polylines():
    assert simplify(((0.0, 0.0),), epsilon=1.0) == ((0.0, 0.0),)
    assert simplify(((0.0, 0.0), (1.0, 1.0)), epsilon=1.0) == ((0.0, 0.0), (1.0, 1.0))


def test_pixels_to_paper_fits_and_centers():
    paper = PaperConfig(width_mm=297.0, height_mm=210.0, margin_mm=10.0)
    polylines = [((0.0, 0.0), (640.0, 480.0))]
    (mapped,) = pixels_to_paper(polylines, 640, 480, paper, mirror=False)
    scale = min(277.0 / 640, 190.0 / 480)
    drawn_w = 640 * scale
    x0 = 10.0 + (277.0 - drawn_w) / 2
    assert mapped[0] == pytest.approx((x0, 10.0))
    assert mapped[1] == pytest.approx((x0 + drawn_w, 200.0))


def test_pixels_to_paper_mirror_flips_x():
    paper = PaperConfig(width_mm=297.0, height_mm=210.0, margin_mm=10.0)
    (plain,) = pixels_to_paper([((0.0, 0.0),)], 640, 480, paper, mirror=False)
    (mirrored,) = pixels_to_paper([((639.0, 0.0),)], 640, 480, paper, mirror=True)
    assert mirrored[0] == pytest.approx(plain[0])


def test_filter_short():
    long = ((0.0, 0.0), (10.0, 0.0))
    short = ((0.0, 0.0), (1.0, 0.0))
    assert filter_short([long, short], min_length=5.0) == [long]


def test_detect_edges_finds_rectangle_boundary():
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.rectangle(frame, (40, 30), (120, 90), (255, 255, 255), thickness=-1)
    edges = detect_edges(frame, VectorizeConfig())
    assert edges.dtype == np.uint8
    assert edges[28:33, 80].max() == 255  # top edge
    assert edges[60, 10:30].max() == 0  # far outside
    assert edges[60, 70:90].max() == 0  # flat interior


def test_vectorize_frame_end_to_end_returns_mm_polylines():
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.rectangle(frame, (40, 30), (120, 90), (255, 255, 255), thickness=-1)
    paper = PaperConfig()
    polylines = vectorize_frame(frame, VectorizeConfig(), paper, mirror=False)
    assert polylines
    for polyline in polylines:
        for x, y in polyline:
            assert paper.margin_mm <= x <= paper.width_mm - paper.margin_mm
            assert paper.margin_mm <= y <= paper.height_mm - paper.margin_mm


def test_split_long_cuts_at_max_length():
    line = tuple((float(x), 0.0) for x in range(0, 101, 10))  # 100 mm, 10 mm segments
    pieces = split_long([line], max_length=30.0)
    assert len(pieces) == 4
    assert pieces[0] == ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0))
    assert pieces[1][0] == (30.0, 0.0)  # pieces share their cut point, so nothing is lost
    assert pieces[-1][-1] == (100.0, 0.0)


def test_split_long_keeps_short_and_single_segment_lines():
    short = ((0.0, 0.0), (5.0, 0.0))
    single_long = ((0.0, 0.0), (500.0, 0.0))
    assert split_long([short, single_long, ()], max_length=30.0) == [short, single_long]
