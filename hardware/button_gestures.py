"""Read taps and holds from timestamped GPIO edges, even during a display refresh."""

import time
from queue import Empty, Queue


class ButtonGestures:
    def __init__(self, hold_seconds, double_tap_seconds):
        self.hold_seconds = hold_seconds
        self.double_tap_seconds = double_tap_seconds
        self.edges = Queue()
        self.pending_edge = None
        self.touch_pending = 0

    def record(self, pressed):
        self.edges.put((pressed, time.monotonic()))

    def touch(self):
        """A touch-sensor press. Wakes a blocked read() so it can report "touch"."""
        self.edges.put((None, time.monotonic()))

    def _edge_before(self, deadline, wake_on_touch=False):
        while True:
            if self.pending_edge is None:
                timeout = None if deadline is None else max(0, deadline - time.monotonic())
                try:
                    self.pending_edge = self.edges.get(timeout=timeout)
                except Empty:
                    return None
            if deadline is not None and self.pending_edge[1] > deadline:
                return None
            edge = self.pending_edge
            self.pending_edge = None
            if edge[0] is None and not wake_on_touch:
                # A touch in the middle of a button gesture: report it on the next read().
                self.touch_pending += 1
                continue
            return edge

    def read(self, *, timeout=None, allow_double_tap=True):
        """Return "tap", "hold", "double_tap", "touch", or None if nothing starts before the timeout."""
        if self.touch_pending:
            self.touch_pending -= 1
            return "touch"
        deadline = None if timeout is None else time.monotonic() + timeout
        edge = self._edge_before(deadline, wake_on_touch=True)
        # A hold is reported before release. Ignore that release on the next read.
        while edge is not None and edge[0] is False:
            edge = self._edge_before(deadline, wake_on_touch=True)
        if edge is None:
            return None
        if edge[0] is None:
            return "touch"

        release = self._edge_before(edge[1] + self.hold_seconds)
        if release is None:
            return "hold"
        if not allow_double_tap:
            return "tap"

        second_press = self._edge_before(release[1] + self.double_tap_seconds)
        if second_press is None:
            return "tap"
        if self._edge_before(second_press[1] + self.hold_seconds) is None:
            return "hold"
        return "double_tap"
