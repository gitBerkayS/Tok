import os
import random
import sys
from functools import lru_cache
from pathlib import Path

from flask import Flask, render_template, jsonify

# Support both python -m interface.app and python interface/app.py.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.token_estimator import estimate_csv

app = Flask(__name__)

REFERENCE_SCALE = 10000  # token budget the UI bar is measured against


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


if __name__ == "__main__":
    app.run(host=os.environ.get("TOK_INTERFACE_HOST", "127.0.0.1"))
