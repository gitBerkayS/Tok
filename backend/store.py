"""Own synchronized capture state, CSV exports, and per-session totals."""

import time
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from threading import Lock

from .analyzer import Features


STALE_AFTER_SECONDS = 6


class ReadingStore:
    """Keep reads, CSV appends, and counter updates consistent across HTTP threads."""

    def __init__(self, feature_csv, vocab_size, submissions_csv=None):
        self.feature_csv = feature_csv
        self.vocab_size = vocab_size
        self.lock = Lock()
        self.reading = {"revision": None, "status": "inactive"}
        self.last_update = None
        self.last_draft_key = None
        self.last_result = None
        self.rows_written = 0
        self.recent_rows = deque(maxlen=20)
        self.submissions_csv = submissions_csv
        self.submission_ids = set()
        self.submitted_chars = 0
        self.started_at = datetime.now(timezone.utc).isoformat()

    def session(self):
        with self.lock:
            return self._session()

    @property
    def submission_tracking_enabled(self):
        return self.submissions_csv is not None

    def _session(self):
        return {
            "started_at": self.started_at,
            "tracking_enabled": self.submission_tracking_enabled,
            "inferred_submissions": len(self.submission_ids),
            "submitted_chars": self.submitted_chars,
        }

    def submit(self, event_id, draft):
        with self.lock:
            if event_id in self.submission_ids:
                return False
            features = Features.from_draft(draft, self.vocab_size)
            self.submissions_csv.append(features)
            self.submission_ids.add(event_id)
            self.submitted_chars += features.chars
            return True

    def current(self):
        with self.lock:
            return self._current()

    def _current(self):
        reading = self.reading.copy()
        if reading.get("source") and time.monotonic() - self.last_update >= STALE_AFTER_SECONDS:
            reading["status"] = "stale"
            reading.pop("features", None)
        return reading

    def dashboard(self):
        with self.lock:
            return {
                "current": self._current(),
                "rows_written": self.rows_written,
                "recent": list(reversed(self.recent_rows)),
                "session": self._session(),
            }

    def update(self, revision, source, status, draft):
        with self.lock:
            last = self.reading["revision"]
            if last is not None and revision <= last:
                return False
            updated_at = datetime.now(timezone.utc).isoformat()
            if status == "ready":
                # Deduplicate refreshes without retaining raw draft text.
                key = (source, sha256(draft.encode("utf-8", errors="surrogatepass")).digest())
                if key == self.last_draft_key:
                    result = self.last_result
                else:
                    features = Features.from_draft(draft, self.vocab_size)
                    feature_values = asdict(features)
                    if draft:
                        self.feature_csv.append(features)
                        self.rows_written += 1
                        self.recent_rows.append({
                            "source": source, "updated_at": updated_at, "features": feature_values,
                        })
                    result = {"status": "ready", "features": feature_values}
                    self.last_draft_key, self.last_result = key, result
            else:
                self.last_draft_key = self.last_result = None
                result = {"status": status}
            self.last_update = time.monotonic()
            self.reading = {
                "revision": revision,
                "source": source,
                "updated_at": updated_at,
                **result,
            }
            return True
