"""Ask Gemini to design the mascot's faces, and save them for the web page and the OLED.

    python hardware/generate_faces.py            # design + save interface/static/faces.json
    python hardware/generate_faces.py --dry-run  # just show them, don't save
    python hardware/generate_faces.py --reset    # delete faces.json -> back to the built-in faces

Re-run it for a fresh set (every run is a new roll). Needs GEMINI_API_KEY in hardware/.env.
Both screens read the same faces.json, so they always match. The key is only needed
HERE; the web server and the Pi just read the saved file.

Faces are lists of pixel rectangles [x, y, w, h] on the mascot's 14x14 grid.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import tok_display as tok  # loads hardware/.env for us

OUT = Path(__file__).resolve().parent.parent / "interface" / "static" / "faces.json"

MOODS = {
    "calm": "usage under 40% of the budget: relaxed, content, plenty of room left",
    "happy": "usage 40-75%: pleased, cheerful, comfortably busy",
    "excited": "usage 75-100%: wired, buzzing, nearly at the limit",
    "maxed": "usage over 100%: overwhelmed, budget blown, wild and stressed",
    "celebrate": "a fresh result just arrived: pure joy, a little party",
}

# Face area on the 14x14 grid: columns 2..11, rows 6..11 (inclusive), inside the body.
X_MIN, X_MAX, Y_MIN, Y_MAX = 2, 12, 6, 12  # rect must satisfy X_MIN<=x, x+w<=X_MAX, Y_MIN<=y, y+h<=Y_MAX
MAX_DARK, MAX_GLINT, MAX_ACCENT = 16, 4, 6

EXAMPLES = {
    "calm": {"dark": [[4, 7, 2, 2], [8, 7, 2, 2], [5, 10, 1, 1], [8, 10, 1, 1], [6, 11, 2, 1]], "glint": []},
    "excited": {"dark": [[4, 6, 2, 3], [8, 6, 2, 3], [6, 10, 2, 2]], "glint": [[4, 6, 1, 1], [8, 6, 1, 1]]},
}

PROMPT = f"""You design pixel-art faces for a cute pumpkin-shaped mascot on a token-usage tracker.
The mascot is a 14x14 pixel grid; its body is a rounded pumpkin. Faces are drawn on the body
as rectangles [x, y, w, h] in whole grid cells. Rules:
- Every rectangle must stay inside columns {X_MIN}..{X_MAX - 1} and rows {Y_MIN}..{Y_MAX - 1}
  (so x >= {X_MIN}, x + w <= {X_MAX}, y >= {Y_MIN}, y + h <= {Y_MAX}).
- "dark": the face features (eyes, mouth, brows, cheeks...) at most {MAX_DARK} rectangles.
- "glint": tiny white highlights drawn on top, at most {MAX_GLINT} rectangles (may be empty).
- "accent": optional yellow details like stars or sparkles, at most {MAX_ACCENT} rectangles (may be empty).
- Keep it readable at 14x14: simple shapes, mostly symmetric eyes, a clear mouth.
- Make every face clearly different from the others, with real personality. Be creative.

Two examples of the format (boring on purpose, do better):
{json.dumps(EXAMPLES)}

Design one face for each mood:
{json.dumps(MOODS, indent=1)}

Reply with ONLY a JSON object: {{"calm": {{"dark": [...], "glint": [...], "accent": [...]}}, "happy": ..., "excited": ..., "maxed": ..., "celebrate": ...}}"""


def ask_gemini(model):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("No GEMINI_API_KEY. Put it in hardware/.env (never commit it).")
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": PROMPT}]}],
            "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json"},
        }
    ).encode()
    request = urllib.request.Request(
        tok.GEMINI_URL.format(model=model),
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        data = json.load(response)
    return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])


def clean_rects(value, limit):
    """Return a validated list of [x,y,w,h] or raise ValueError."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"expected a list of at most {limit} rectangles")
    rects = []
    for item in value:
        if not (isinstance(item, list) and len(item) == 4 and all(isinstance(n, int) and not isinstance(n, bool) for n in item)):
            raise ValueError(f"bad rectangle {item!r}")
        x, y, w, h = item
        if w < 1 or h < 1 or x < X_MIN or y < Y_MIN or x + w > X_MAX or y + h > Y_MAX:
            raise ValueError(f"rectangle {item!r} is outside the face area")
        rects.append([x, y, w, h])
    return rects


def clean_face(face):
    dark = clean_rects(face.get("dark"), MAX_DARK)
    glint = clean_rects(face.get("glint"), MAX_GLINT)
    accent = clean_rects(face.get("accent"), MAX_ACCENT)
    cells = {(x + i, y + j) for x, y, w, h in dark for i in range(w) for j in range(h)}
    if len(cells) < 4:
        raise ValueError("face is nearly empty")
    if not any(y < 9 for _, y in cells) or not any(y >= 9 for _, y in cells):
        raise ValueError("face needs both eyes (upper) and a mouth (lower)")
    return {"dark": dark, "glint": glint, "accent": accent}


def preview(name, face):
    grid = [["." for _ in range(14)] for _ in range(14)]
    for x, y, w, h in [(1, 5, 12, 7)]:  # rough body block, for context
        for i in range(w):
            for j in range(h):
                grid[y + j][x + i] = "+"
    for key, ch in (("dark", "#"), ("accent", "*"), ("glint", "o")):
        for x, y, w, h in face[key]:
            for i in range(w):
                for j in range(h):
                    grid[y + j][x + i] = ch
    print(f"{name}  ({MOODS[name].split(':')[0]})")
    for row in grid[4:13]:
        print("   " + " ".join(row))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=os.environ.get("GEMINI_FACE_MODEL", "gemini-2.5-flash"))
    parser.add_argument("--dry-run", action="store_true", help="show the faces, don't save")
    parser.add_argument("--reset", action="store_true", help="delete faces.json (use built-in faces)")
    args = parser.parse_args()

    if args.reset:
        OUT.unlink(missing_ok=True)
        print(f"Removed {OUT}; both screens use their built-in faces again.")
        return

    faces, problems = {}, []
    for attempt in range(1, 4):
        try:
            raw = ask_gemini(args.model)
        except (OSError, ValueError, KeyError, IndexError, urllib.error.URLError) as error:
            problems.append(f"attempt {attempt}: {error}")
            time.sleep(2)
            continue
        for mood in MOODS:
            if mood in faces:
                continue
            try:
                faces[mood] = clean_face(raw[mood])
            except (KeyError, ValueError, AttributeError) as error:
                problems.append(f"attempt {attempt}, {mood}: {error}")
        if len(faces) == len(MOODS):
            break

    if len(faces) != len(MOODS):
        print("Gemini did not give a full valid set:", *problems, sep="\n  ")
        sys.exit("Nothing saved; the screens keep their current faces.")

    for mood in MOODS:
        preview(mood, faces[mood])
    if problems:
        print("\n(retried:", "; ".join(problems), ")")
    if args.dry_run:
        print("\nDry run: nothing saved.")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "model": args.model, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "faces": faces}
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"\nSaved {OUT}")


if __name__ == "__main__":
    main()
