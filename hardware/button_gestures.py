"""Read taps and holds from timestamped GPIO edges, even during a display refresh."""

import time
from queue import Empty, Queue


class ButtonGestures:
    def __init__(self, hold_seconds, double_tap_seconds):
        self.hold_seconds = hold_seconds
        self.double_tap_seconds = double_tap_seconds
        self.edges = Queue()
        self.pending_edge = None

    def record(self, pressed):
        self.edges.put((pressed, time.monotonic()))

    def _edge_before(self, deadline):
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
        return edge

    def read(self, *, timeout=None, allow_double_tap=True):
        """Return a gesture or None if no press starts before the timeout."""
        deadline = None if timeout is None else time.monotonic() + timeout
        edge = self._edge_before(deadline)
        # A hold is reported before release. Ignore that release on the next read.
        while edge is not None and not edge[0]:
            edge = self._edge_before(deadline)
        if edge is None:
            return None

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
