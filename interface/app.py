import json
import os
import random
import sys
import time
from functools import lru_cache
from pathlib import Path
from urllib.request import urlopen

from flask import Flask, Response, render_template, jsonify

# Support both python -m interface.app and python interface/app.py.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analyzer import Features
from backend.token_estimator import estimate_csv, estimate_tokens

app = Flask(__name__)

REFERENCE_SCALE = 10000  # token budget the UI bar is measured against
DRAFT_REFRESH_SECONDS = 0.5
DRAFT_KEEPALIVE_SECONDS = 15
DRAFT_ERROR = "Live draft estimate unavailable"


@lru_cache(maxsize=1)
def _csv_token_total(path, vocab_size, file_version):
    # The file version changes on append and on atomic startup reset.
    return estimate_csv(path, vocab_size)["estimated_tokens"]


def get_token_count():
    """Return the configured submission CSV estimate, or the demo count."""
    csv_path = os.environ.get("TOK_SUBMISSIONS_CSV")
    if csv_path:
        vocab = os.environ.get("TOK_VOCAB_SIZE")
        stat = Path(csv_path).stat()
        version = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        return _csv_token_total(csv_path, int(vocab) if vocab else None, version)
    # Preserve demo mode when no capture file is configured.
    return random.randint(300, 55000)


@app.route("/")
def home():
    return render_template("index.html", reference_scale=REFERENCE_SCALE)


@app.route("/api/usage")
def get_usage():
    try:
        return jsonify(tokens=get_token_count(), scale=REFERENCE_SCALE)
    except (OSError, ValueError, RuntimeError) as error:
        return jsonify(error=str(error)), 503


@lru_cache(maxsize=64)
def _draft_estimate(features):
    return estimate_tokens(features)


def _live_draft():
    """Read the same capture snapshot used by the monitor and estimate its tokens."""
    port = int(os.environ.get("TOK_CAPTURE_PORT", "8765"))
    with urlopen(f"http://127.0.0.1:{port}/reading", timeout=1) as response:
        reading = json.load(response)
    status = reading["status"]
    result = {
        "tokens": 0,
        "scale": REFERENCE_SCALE,
        "status": status,
        "source": reading.get("source"),
        "revision": reading.get("revision"),
        "updated_at": reading.get("updated_at"),
    }
    if status == "ready":
        values = reading["features"]
        features = Features(**values)
        vocab = os.environ.get("TOK_VOCAB_SIZE")
        if features.vocab_size is None and vocab:
            features = Features(**{**values, "vocab_size": int(vocab)})
        estimate = _draft_estimate(features)
        result.update(tokens=estimate["estimated_tokens"], method=estimate["method"],
                      features=values)
    return result


def _live_draft_response():
    try:
        return _live_draft(), 200
    except (OSError, KeyError, TypeError, ValueError, RuntimeError):
        return {"error": DRAFT_ERROR}, 503


@app.route("/api/draft")
def get_draft_usage():
    """Return the latest live draft as a JSON snapshot."""
    payload, status = _live_draft_response()
    return jsonify(payload), status, {"Cache-Control": "no-store"}


@app.route("/api/draft/stream")
def stream_draft_usage():
    """Send the initial draft and subsequent capture updates on one connection."""
    def events():
        previous = None
        last_sent = time.monotonic()
        while True:
            payload, status = _live_draft_response()
            now = time.monotonic()
            if payload != previous:
                event = "draft" if status == 200 else "capture-error"
                previous = payload
                last_sent = now
                yield f"event: {event}\ndata: {json.dumps(payload)}\n\n"
            elif now - last_sent >= DRAFT_KEEPALIVE_SECONDS:
                last_sent = now
                yield ": keepalive\n\n"
            time.sleep(DRAFT_REFRESH_SECONDS)

    return Response(events(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    app.run(host=os.environ.get("TOK_INTERFACE_HOST", "127.0.0.1"))
