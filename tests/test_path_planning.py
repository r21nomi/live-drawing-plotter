from live_plotter.config import PaperConfig
from live_plotter.ink_canvas import InkCanvas
from live_plotter.path_planning import order_strokes, select_strokes

PAPER = PaperConfig(width_mm=300.0, height_mm=200.0, margin_mm=10.0)


def _hline(y, x0=20.0, x1=120.0):
    return ((x0, y), (x1, y))


def _empty():
    return InkCanvas.empty(PAPER, px_per_mm=2.0)


def test_select_respects_length_budget():
    candidates = [_hline(20.0 + 20 * i) for i in range(5)]  # 100 mm each
    selected = select_strokes(candidates, _empty(), budget_mm=250.0, min_novelty=0.3, ink_radius_mm=1.0)
    assert len(selected) == 2


def test_select_prefers_novel_strokes():
    drawn = _hline(20.0)
    fresh = _hline(60.0)
    canvas = _empty().with_strokes([drawn], radius_mm=1.0)
    selected = select_strokes([drawn, fresh], canvas, budget_mm=100.0, min_novelty=0.3, ink_radius_mm=1.0)
    assert selected == [fresh]


def test_select_skips_strokes_below_min_novelty():
    drawn = _hline(20.0)
    canvas = _empty().with_strokes([drawn], radius_mm=1.0)
    selected = select_strokes([drawn], canvas, budget_mm=1000.0, min_novelty=0.3, ink_radius_mm=1.0)
    assert selected == []


def test_select_suppresses_near_duplicates_within_one_cycle():
    a = _hline(20.0)
    b = _hline(20.5)
    selected = select_strokes([a, b], _empty(), budget_mm=1000.0, min_novelty=0.3, ink_radius_mm=1.0)
    assert len(selected) == 1


def test_select_prefers_longer_novel_strokes():
    long = _hline(20.0, 20.0, 220.0)
    short = _hline(60.0, 20.0, 40.0)
    selected = select_strokes([short, long], _empty(), budget_mm=200.0, min_novelty=0.3, ink_radius_mm=1.0)
    assert selected[0] == long


def test_select_empty_candidates():
    assert select_strokes([], _empty(), budget_mm=100.0, min_novelty=0.3, ink_radius_mm=1.0) == []


def test_order_visits_nearest_first():
    near = ((10.0, 10.0), (20.0, 10.0))
    far = ((200.0, 100.0), (210.0, 100.0))
    assert order_strokes([far, near], start=(0.0, 0.0)) == [near, far]


def test_order_reverses_stroke_when_end_is_closer():
    stroke = ((100.0, 0.0), (0.0, 0.0))
    (ordered,) = order_strokes([stroke], start=(0.0, 0.0))
    assert ordered == ((0.0, 0.0), (100.0, 0.0))
    assert stroke == ((100.0, 0.0), (0.0, 0.0))


def test_order_chains_from_previous_stroke_end():
    a = ((0.0, 0.0), (50.0, 0.0))
    b = ((52.0, 0.0), (60.0, 0.0))
    c = ((5.0, 30.0), (10.0, 30.0))
    # from the end of b (60, 0) the end of c (10, 30) is closer than its start, so c is reversed
    assert order_strokes([c, b, a], start=(0.0, 0.0)) == [a, b, ((10.0, 30.0), (5.0, 30.0))]
