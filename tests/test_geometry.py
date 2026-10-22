from live_plotter.geometry import distance, polyline_length, reversed_polyline, total_length


def test_distance():
    assert distance((0.0, 0.0), (3.0, 4.0)) == 5.0


def test_polyline_length():
    assert polyline_length(((0.0, 0.0), (3.0, 4.0), (3.0, 10.0))) == 11.0
    assert polyline_length(((1.0, 1.0),)) == 0.0


def test_total_length():
    assert total_length([((0.0, 0.0), (1.0, 0.0)), ((0.0, 0.0), (0.0, 2.0))]) == 3.0


def test_reversed_polyline_returns_new_tuple():
    original = ((0.0, 0.0), (1.0, 0.0))
    assert reversed_polyline(original) == ((1.0, 0.0), (0.0, 0.0))
    assert original == ((0.0, 0.0), (1.0, 0.0))
