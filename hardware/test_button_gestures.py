"""Tiny checks for ButtonGestures (no GPIO needed):  python hardware/test_button_gestures.py"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from button_gestures import ButtonGestures  # noqa: E402


def make():
    return ButtonGestures(hold_seconds=0.4, double_tap_seconds=0.2)


def later(delay, fn, *args):
    threading.Timer(delay, fn, args).start()


def test_touch_wakes_a_blocked_read():
    g = make()
    later(0.05, g.touch)
    assert g.read(allow_double_tap=False) == "touch"


def test_single_tap_and_hold():
    g = make()
    later(0.02, g.record, True)
    later(0.06, g.record, False)
    assert g.read(allow_double_tap=False) == "tap"
    later(0.02, g.record, True)  # held down, never released within hold_seconds
    assert g.read(allow_double_tap=False) == "hold"
    g.record(False)  # the release after a hold is ignored by the next read
    assert g.read(timeout=0.1, allow_double_tap=False) is None


def test_touch_during_a_button_press_is_not_lost_or_confused():
    g = make()
    later(0.02, g.record, True)
    later(0.05, g.touch)  # touch while the button is down
    later(0.08, g.record, False)
    assert g.read(allow_double_tap=False) == "tap"  # the button gesture is still a clean tap
    assert g.read(timeout=0.1, allow_double_tap=False) == "touch"  # and the touch is reported next


def test_two_touches_toggle_twice():
    g = make()
    g.touch()
    time.sleep(0.01)
    g.touch()
    assert [g.read(timeout=0.1, allow_double_tap=False) for _ in range(2)] == ["touch", "touch"]


def test_timeout_returns_none():
    assert make().read(timeout=0.05, allow_double_tap=False) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
