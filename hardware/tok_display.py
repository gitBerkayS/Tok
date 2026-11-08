"""Hardware-independent core of the TOK 16x2 display.

Everything about WHAT the display shows lives here, so the same code drives
the browser simulator (simulator.py) and the real Raspberry Pi LCD (lcd_button.py).

    Line 1: token count and %      e.g.  25,316 tok   51%
    Line 2: short comment on it    e.g.  Nice and steady   (written by Gemini)

Only the standard library is used, so it runs anywhere.

Gemini setup (optional, falls back to canned comments without it):
    put  GEMINI_API_KEY=...  in hardware/.env  (or export it in your shell)
"""
import json
import math
import os
import random
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

WIDTH = 16  # characters per LCD row

DEFAULT_SCALE = 50000  # used if the API returns only a bare number

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_TIMEOUT = 4  # seconds; the display must never hang on the network

# Same thresholds and colours as the web interface, checked top-down.
# (min ratio, name, backlight RGB, canned comments <= 16 chars, plain ASCII)
LEVELS = [
    (1.0, "over", (255, 0, 40), ["Over the limit!", "Way too many!", "Trim that prompt", "Budget blown :("]),
    (0.75, "high", (255, 120, 0), ["Getting heavy!", "Big prompt alert", "Near the limit", "Easy there..."]),
    (0.4, "mid", (192, 38, 211), ["Nice and steady", "Moderate usage", "Looking healthy", "Right on track"]),
    (0.0, "low", (139, 92, 246), ["Light & lean :)", "Barely a nibble", "Easy on tokens", "Super efficient"]),
]

# Backlight colours for non-usage states.
IDLE_RGB = (110, 40, 180)
BUSY_RGB = (180, 120, 0)
ERROR_RGB = (220, 20, 30)


# ---------- config ----------
def load_env(path=None):
    """Tiny .env reader (KEY=value lines) so no python-dotenv is needed.

    Real environment variables win over the file.
    """
    path = Path(path) if path else Path(__file__).with_name(".env")
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()
API_URL = os.environ.get("TOK_API_URL", "http://127.0.0.1:5000/api/usage")


# ---------- usage ----------
def parse_usage(data):
    """Accept {"tokens": n, "scale": s} or a bare number. Returns (tokens, scale)."""
    if isinstance(data, dict):
        tokens, scale = data.get("tokens"), data.get("scale") or DEFAULT_SCALE
    else:
        tokens, scale = data, DEFAULT_SCALE
    if (
        isinstance(tokens, bool)
        or not isinstance(tokens, (int, float))
        or not math.isfinite(tokens)
        or tokens < 0
    ):
        raise ValueError("Invalid token count")
    return round(tokens), scale


def fetch_usage(url=None):
    """GET the usage API. Returns (tokens, scale); raises OSError/ValueError on failure."""
    with urllib.request.urlopen(url or API_URL, timeout=5) as response:
        return parse_usage(json.load(response))


def level_for(tokens, scale):
    ratio = tokens / scale
    return next(level for level in LEVELS if ratio >= level[0])


def usage_line(tokens, scale):
    pct = f"{tokens / scale * 100:.0f}%"
    left = f"{tokens:,} tok"
    if len(left) + 1 + len(pct) > WIDTH:  # very large numbers: drop "tok" to keep a gap
        left = f"{tokens:,}"
    return left + pct.rjust(WIDTH - len(left))


# ---------- comments ----------
def clean_comment(text):
    """Make model output safe for a 16-char ASCII LCD row (or return None)."""
    lines = (text or "").strip().splitlines()
    text = lines[0].strip(" \"'`*") if lines else ""
    text = text.encode("ascii", "ignore").decode()
    text = " ".join(text.split())
    if not text:
        return None
    if len(text) > WIDTH:
        # cut at a word boundary if we can, else hard-cut
        cut = text[:WIDTH]
        text = cut.rsplit(" ", 1)[0] if " " in cut.strip() else cut
    return text[:WIDTH].rstrip() or None


def gemini_comment(tokens, scale, avoid=None):
    """Ask Gemini for a short comment. Returns a clean string, or None on any problem."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    pct = tokens / scale * 100
    prompt = (
        "You write the second line of a tiny 16-character LCD on an AI token "
        f"usage tracker. Usage is {tokens:,} of a {scale:,} token budget ({pct:.0f}%). "
        "Reply with ONE witty, friendly comment on that usage: at most 16 characters, "
        "plain ASCII, no emoji, no quotes, no trailing period needed."
    )
    if avoid:
        prompt += f' Do not repeat: "{avoid}".'
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 40,
                "temperature": 1.0,
                # Keep 2.5-style "thinking" from eating the tiny output budget.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
    ).encode()
    request = urllib.request.Request(
        GEMINI_URL.format(model=GEMINI_MODEL),
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=GEMINI_TIMEOUT) as response:
            data = json.load(response)
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (OSError, ValueError, KeyError, IndexError, urllib.error.URLError):
        return None
    return clean_comment(text)


def canned_comment(tokens, scale, avoid=None):
    comments = level_for(tokens, scale)[3]
    return random.choice([c for c in comments if c != avoid] or comments)


# ---------- the frame ----------
@dataclass
class Frame:
    line1: str
    line2: str
    rgb: tuple
    source: str  # "gemini", "canned" or "error: ..." - handy for the simulator
    level: str = ""  # "low" | "mid" | "high" | "over" (empty on errors)


_last_comment = None


def build_frame(tokens, scale):
    """Everything the display needs for one refresh."""
    global _last_comment
    comment = gemini_comment(tokens, scale, _last_comment)
    source = "gemini"
    if comment is None:
        comment, source = canned_comment(tokens, scale, _last_comment), "canned"
    _last_comment = comment
    _, level, rgb, _ = level_for(tokens, scale)
    return Frame(usage_line(tokens, scale), comment, rgb, source, level)


def refresh_frame(url=None):
    """Fetch usage and build a Frame; on failure return an error Frame instead of raising."""
    try:
        tokens, scale = fetch_usage(url)
    except (OSError, ValueError) as error:  # URLError is an OSError
        return Frame("TOK", "Refresh failed", ERROR_RGB, f"error: {error}")
    return build_frame(tokens, scale)
