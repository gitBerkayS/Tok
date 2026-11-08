import hmac
import json
import os
import random
import sys
import time
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from urllib.request import urlopen

from flask import Flask, Response, render_template, jsonify, request

# Support both python -m interface.app and python interface/app.py.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analyzer import Features
from backend.token_estimator import estimate_csv, estimate_tokens

app = Flask(__name__)

REFERENCE_SCALE = 5000  # token budget the UI bar is measured against
DRAFT_REFRESH_SECONDS = 0.5
DRAFT_KEEPALIVE_SECONDS = 15
RESET_LOCK = Lock()
DRAFT_ERROR = "Live draft estimate unavailable"


@lru_cache(maxsize=1)
def _csv_token_total(path, vocab_size, file_version, cutoff):
    # File version changes on append and replacement. The cutoff changes on reset.
    estimate = estimate_csv(path, vocab_size, cutoff=cutoff)
    if os.environ.get("TOK_DIAGNOSTICS") == "1":
        device, inode, size, _ = file_version
        active_cutoff = cutoff[2] if cutoff and cutoff[:2] == (device, inode) and cutoff[2] <= size else 0
        app.logger.warning(
            "tok usage device=%d inode=%d csv_bytes=%d reset_offset=%d rows=%d tokens=%d",
            device, inode, size, active_cutoff, len(estimate["rows"]), estimate["estimated_tokens"],
        )
    return estimate["estimated_tokens"]


def _cutoff_path(csv_path):
    return Path(f"{csv_path}.reset")


def _read_cutoff(csv_path):
    try:
        device, inode, offset = json.loads(_cutoff_path(csv_path).read_text())
    except FileNotFoundError:
        return None
    if any(type(value) is not int or value < 0 for value in (device, inode, offset)):
        raise ValueError("Invalid usage reset cutoff.")
    return device, inode, offset


def _save_cutoff(csv_path):
    target = _cutoff_path(csv_path)
    with RESET_LOCK, open(csv_path, "rb") as source:
        stat = os.fstat(source.fileno())
        # Only cut at a complete numeric line.
        if stat.st_size == 0:
            raise ValueError("Submission CSV has no header.")
        source.seek(stat.st_size - 1)
        if source.read(1) != b"\n":
            raise ValueError("Submission CSV ends in a partial record.")
        with NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            try:
                json.dump([stat.st_dev, stat.st_ino, stat.st_size], output)
                output.flush()
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)


def get_token_count():
    """Return the configured submission CSV estimate, or the demo count."""
    csv_path = os.environ.get("TOK_SUBMISSIONS_CSV")
    if csv_path:
        vocab = os.environ.get("TOK_VOCAB_SIZE")
        cutoff = _read_cutoff(csv_path)
        stat = Path(csv_path).stat()
        version = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        return _csv_token_total(csv_path, int(vocab) if vocab else None, version, cutoff)
    # Preserve demo mode when no capture file is configured.
    return random.randint(300, 55000)


@app.route("/")
def home():
    return render_template("index.html", reference_scale=REFERENCE_SCALE)


@app.route("/api/usage")
def get_usage():
    try:
        return jsonify(tokens=get_token_count(), scale=REFERENCE_SCALE)
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        if os.environ.get("TOK_DIAGNOSTICS") == "1":
            app.logger.warning("tok usage failed type=%s errno=%s", type(error).__name__, getattr(error, "errno", None))
        return jsonify(error=str(error)), 503


@app.post("/api/usage/reset")
def reset_usage():
    csv_path = os.environ.get("TOK_SUBMISSIONS_CSV")
    secret = os.environ.get("TOK_RESET_KEY")
    if not csv_path or not secret:
        return jsonify(error="Usage reset is disabled"), 503
    authorization = request.headers.get("Authorization", "")
    if not hmac.compare_digest(authorization.encode(), f"Bearer {secret}".encode()):
        return jsonify(error="Invalid reset key"), 403
    try:
        _save_cutoff(csv_path)
    except (OSError, ValueError) as error:
        return jsonify(error=str(error)), 503
    return jsonify(tokens=0, scale=REFERENCE_SCALE), 200, {"Cache-Control": "no-store"}


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
