from live_plotter.controls import Phase, RunControl


def test_starts_running_by_default():
    control = RunControl()
    assert control.paused is False
    assert control.phase == Phase.STARTING


def test_can_start_paused_waiting_for_the_start_button():
    control = RunControl(paused=True)
    assert control.paused is True
    control.request_resume()
    assert control.paused is False


def test_pause_and_resume():
    control = RunControl()
    control.request_pause()
    assert control.paused is True
    control.request_resume()
    assert control.paused is False


def test_new_paper_pauses_and_is_consumed_once():
    control = RunControl()
    control.request_new_paper()
    assert control.paused is True
    assert control.take_new_paper_request() is True
    assert control.take_new_paper_request() is False
    assert control.paused is True  # stays paused until the operator resumes


def test_phase_is_tracked():
    control = RunControl()
    control.set_phase(Phase.DRAWING)
    assert control.phase == Phase.DRAWING
    assert control.snapshot() == {"phase": "drawing", "paused": False}
