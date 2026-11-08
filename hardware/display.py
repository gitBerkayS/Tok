"""TOK hardware display.

Polls the TOK Flask backend (/api/usage) and shows the latest prediction on
whatever is attached to the Raspberry Pi:

  oled     0.96" SSD1306 OLED, 128x64, I2C  -> pixel mascot + number + bar
  lcd      Grove 16x2 LCD (RGB backlight), I2C -> text + mood-coloured backlight
  preview  no hardware: writes the OLED frame to preview.png
  console  always on: prints each new reading (handy over SSH)

Run (on the Pi, Flask on a laptop):
    python display.py --url http://<laptop-ip>:5000/api/usage
Run (on a laptop, no hardware):
    python display.py --display preview
"""
import argparse
import json
import math
import threading
import time
import urllib.request
from pathlib import Path

CELEBRATE_S = 1.6  # how long the star-eyed bounce lasts after a new number
FPS = 8

# Same thresholds and moods as the web interface (interface/static/script.js).
FACE_FOR_LEVEL = {"low": "calm", "mid": "happy", "high": "excited", "over": "maxed"}
LCD_FACE = {
    "calm": "(o.o)", "happy": "(^_^)", "excited": "(O_O)", "maxed": "(@_@)",
    "celebrate": "(*o*)", "loading": "(._.)", "error": "(x_x)",
}
LCD_RGB = {
    "low": (139, 92, 246), "mid": (192, 38, 211), "high": (255, 120, 0),
    "over": (255, 0, 40), "error": (60, 60, 60),
}


def level_for(ratio):
    if ratio >= 1:
        return "over"
    if ratio >= 0.75:
        return "high"
    if ratio >= 0.4:
        return "mid"
    return "low"


# ---------- mascot pixels: same 14x14 grid as the web SVG, as (x, y, w, h) ----------
BODY = [(6, 0, 2, 1), (6, 1, 2, 2), (4, 3, 6, 1), (2, 4, 10, 1), (1, 5, 12, 7),
        (2, 12, 10, 1), (3, 13, 2, 1), (9, 13, 2, 1)]
SMILE = [(5, 10, 4, 1), (6, 11, 2, 1)]
FACES = {  # face -> (dark pixels, white glint pixels drawn on top)
    "calm": ([(4, 7, 2, 2), (8, 7, 2, 2), (5, 10, 1, 1), (8, 10, 1, 1), (6, 11, 2, 1)], []),
    "happy": ([(3, 8, 1, 1), (4, 7, 1, 1), (5, 8, 1, 1), (10, 8, 1, 1), (9, 7, 1, 1), (8, 8, 1, 1)] + SMILE, []),
    "excited": ([(4, 6, 2, 3), (8, 6, 2, 3), (6, 10, 2, 2)], [(4, 6, 1, 1), (8, 6, 1, 1)]),
    "maxed": ([(3, 6, 3, 3), (8, 6, 3, 3), (5, 10, 4, 2)], [(4, 7, 1, 1), (9, 7, 1, 1)]),
    "celebrate": ([(4, 6, 1, 1), (3, 7, 3, 1), (4, 8, 1, 1), (9, 6, 1, 1), (8, 7, 3, 1), (9, 8, 1, 1)] + SMILE, []),
    "loading": ([(4, 7, 2, 2), (8, 7, 2, 2), (6, 10, 2, 1)], []),
    "error": ([(3, 6, 1, 1), (5, 6, 1, 1), (4, 7, 1, 1), (3, 8, 1, 1), (5, 8, 1, 1),
               (8, 6, 1, 1), (10, 6, 1, 1), (9, 7, 1, 1), (8, 8, 1, 1), (10, 8, 1, 1),
               (6, 10, 2, 1), (5, 11, 1, 1), (8, 11, 1, 1)], []),
}


def load_designed_faces():
    """Use the Gemini-designed faces from interface/static/faces.json if present and valid.

    Same file the web page reads, so both screens match. Anything wrong with it and the
    built-in faces above stay untouched.
    """
    path = Path(__file__).resolve().parent.parent / "interface" / "static" / "faces.json"
    try:
        faces = json.loads(path.read_text())["faces"]
        parsed = {}
        for name, face in faces.items():
            if name not in FACES:
                continue
            rects = {}
            for kind in ("dark", "accent", "glint"):
                rects[kind] = [tuple(r) for r in face.get(kind, [])]
                for r in rects[kind]:
                    if len(r) != 4 or not all(isinstance(n, int) for n in r) or r[2] < 1 or r[3] < 1 \
                            or r[0] < 0 or r[1] < 0 or r[0] + r[2] > 14 or r[1] + r[3] > 14:
                        raise ValueError(f"bad rectangle {r}")
            # On the 1-bit OLED the yellow accents are just more dark pixels.
            parsed[name] = (rects["dark"] + rects["accent"], rects["glint"])
        FACES.update(parsed)
        print(f"[TOK] designed faces loaded: {', '.join(parsed)}")
    except FileNotFoundError:
        pass
    except Exception as err:
        print(f"[TOK] faces.json ignored ({err}); using built-in faces")


load_designed_faces()


# ---------- shared state, filled by the polling thread ----------
class State:
    def __init__(self):
        self.tokens = None
        self.token_label = "tokens"
        self.scale = 5000
        self.status = "loading"  # loading | ok | error
        self.error = ""
        self.changed_at = 0.0

    @property
    def ratio(self):
        return (self.tokens or 0) / self.scale

    @property
    def level(self):
        return level_for(self.ratio)

    def face(self, now):
        if self.status == "error":
            return "error"
        if self.tokens is None:
            return "loading"
        if now - self.changed_at < CELEBRATE_S:
            return "celebrate"
        return FACE_FOR_LEVEL[self.level]


def poll(url, interval, state):
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as res:
                data = json.load(res)
            # Accept either {tokens, scale} or a bare number, like the web UI.
            payload = data if isinstance(data, dict) else {"tokens": data}
            tokens = int(payload["tokens"])
            state.scale = int(payload.get("scale") or state.scale)
            if tokens != state.tokens:
                state.changed_at = time.monotonic()
            state.tokens, state.status = tokens, "ok"
        except Exception as err:
            state.status, state.error = "error", str(err)
        time.sleep(interval)


# ---------- OLED frame (also used by preview) ----------
_font_cache = {}


def load_font(size):
    if size in _font_cache:
        return _font_cache[size]
    from PIL import ImageFont
    font = None
    for name in ("DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        try:
            font = ImageFont.truetype(name, size)
            break
        except OSError:
            pass
    if font is None:
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:  # Pillow < 10.1
            font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def fit_font(draw, text, max_w, largest=22, smallest=9):
    for size in range(largest, smallest - 1, -1):
        font = load_font(size)
        if draw.textlength(text, font=font) <= max_w:
            return font
    return load_font(smallest)


def draw_mascot(draw, face, ox, oy, s, now):
    def rects(items, fill, shift=0):
        for x, y, w, h in items:
            draw.rectangle([ox + x * s + shift, oy + y * s,
                            ox + (x + w) * s - 1 + shift, oy + (y + h) * s - 1], fill=fill)

    rects(BODY, 255)
    dark, glint = FACES[face]
    if face == "loading":  # eyes glance left/right
        shift = -(s // 2) if int(now * 1.4) % 2 == 0 else s // 2
        rects(dark[:2], 0, shift)
        rects(dark[2:], 0)
    else:
        rects(dark, 0)
    rects(glint, 255)


def render_frame(state, now):
    from PIL import Image, ImageDraw
    img = Image.new("1", (128, 64), 0)
    d = ImageDraw.Draw(img)
    face = state.face(now)

    # Mascot on the left, 14px grid at 4x = 56px.
    if face == "celebrate":
        bob = -int(abs(math.sin(now * 9)) * 6)
    elif face in ("excited", "maxed"):
        bob = -int((math.sin(now * 6) + 1) * 1.5)
    elif face == "error":
        bob = 0
    else:
        bob = -int((math.sin(now * 2) + 1) * 1.5)
    jitter = 1 if face == "maxed" and int(now * 12) % 2 else 0
    draw_mascot(d, face, 2 + jitter, 6 + bob, 4, now)

    # Number panel on the right.
    x0, right = 64, 127
    small = load_font(10)
    d.text((x0, 0), "TOK", font=small, fill=255)
    if state.tokens is not None:
        pct = f"{state.ratio * 100:.0f}%"
        d.text((right - d.textlength(pct, font=small), 0), pct, font=small, fill=255)

    num = f"{state.tokens:,}" if state.tokens is not None else "--"
    d.text((x0, 16), num, font=fit_font(d, num, right - x0), fill=255)

    label = "offline" if state.status == "error" else (state.token_label if state.tokens is not None else "waiting")
    d.text((x0, 38), label, font=small, fill=255)

    d.rectangle([x0, 52, right, 60], outline=255)
    fill_w = int((right - x0 - 3) * min(state.ratio, 1))
    if fill_w > 0:
        d.rectangle([x0 + 2, 54, x0 + 1 + fill_w, 58], fill=255)
    return img


# ---------- outputs ----------
class OledDisplay:
    def __init__(self, bus, addr, driver):
        from luma.core.interface.serial import i2c
        from luma.oled import device as oled
        self.device = getattr(oled, driver)(i2c(port=bus, address=addr))

    def show(self, state, now):
        self.device.display(render_frame(state, now))


class PreviewDisplay:
    def __init__(self, path):
        self.path = path
        self.next_save = 0.0

    def show(self, state, now):
        if now < self.next_save:
            return
        self.next_save = now + 0.5
        from PIL import Image
        render_frame(state, now).resize((512, 256), Image.NEAREST).save(self.path)


class LcdDisplay:
    TEXT_ADDR = 0x3E

    def __init__(self, bus):
        from smbus2 import SMBus
        self.bus = SMBus(bus)
        self._cmd(0x01)  # clear
        time.sleep(0.05)
        self._cmd(0x08 | 0x04)  # display on, no cursor
        self._cmd(0x28)  # two lines
        time.sleep(0.05)
        self.rgb_addr = self._init_backlight()
        self.last = None

    def _cmd(self, c):
        self.bus.write_byte_data(self.TEXT_ADDR, 0x80, c)

    def _write_line(self, row, text):
        self._cmd(0x80 if row == 0 else 0xC0)
        for ch in text.ljust(16)[:16]:
            self.bus.write_byte_data(self.TEXT_ADDR, 0x40, ord(ch))

    def _init_backlight(self):
        try:  # RGB backlight v4 and older
            for reg, val in ((0x00, 0x00), (0x08, 0xFF), (0x01, 0x20)):
                self.bus.write_byte_data(0x62, reg, val)
            return 0x62
        except OSError:
            pass
        try:  # RGB backlight v5
            self.bus.write_byte_data(0x30, 0x00, 0x07)
            time.sleep(0.001)
            self.bus.write_byte_data(0x30, 0x04, 0x15)
            return 0x30
        except OSError:
            return None  # plain Grove 16x2 LCD: no colour control

    def _color(self, rgb):
        regs = (0x04, 0x03, 0x02) if self.rgb_addr == 0x62 else (0x06, 0x07, 0x08)
        for reg, val in zip(regs, rgb):
            self.bus.write_byte_data(self.rgb_addr, reg, val)

    def show(self, state, now):
        face = state.face(now)
        line1 = "TOK" + LCD_FACE[face].rjust(13)
        if state.tokens is None:
            line2 = "no connection" if state.status == "error" else "connecting..."
        else:
            left = f"{state.tokens:,} tok"
            line2 = left + f"{state.ratio * 100:.0f}%".rjust(16 - len(left))
        rgb = LCD_RGB["error" if state.status == "error" else state.level]
        if (line1, line2, rgb) == self.last:
            return  # I2C is slow; only write on change
        self._write_line(0, line1)
        self._write_line(1, line2)
        if self.rgb_addr and (self.last is None or self.last[2] != rgb):
            self._color(rgb)
        self.last = (line1, line2, rgb)


class ConsoleDisplay:
    def __init__(self):
        self.last = None

    def show(self, state, now):
        key = (state.tokens, state.status)
        if key == self.last:
            return
        self.last = key
        if state.status == "error":
            print(f"[TOK] (x_x) connection error: {state.error}", flush=True)
        elif state.tokens is not None:
            bar = "#" * round(min(state.ratio, 1) * 20)
            face = LCD_FACE[FACE_FOR_LEVEL[state.level]]
            print(f"[TOK] {face} {state.tokens:>7,} tokens {state.ratio * 100:6.1f}% "
                  f"[{bar:<20}] {state.level}", flush=True)


# ---------- main ----------
def build_displays(args):
    wanted = set(args.display or ["auto"])
    auto = "auto" in wanted
    displays = [ConsoleDisplay()]
    makers = {
        "oled": lambda: OledDisplay(args.i2c_bus, args.oled_addr, args.oled_driver),
        "lcd": lambda: LcdDisplay(args.i2c_bus),
    }
    for name, make in makers.items():
        if auto or name in wanted:
            try:
                displays.append(make())
                print(f"[TOK] {name}: ready")
            except Exception as err:
                if not auto:
                    raise SystemExit(f"[TOK] {name}: failed to start ({err})")
                print(f"[TOK] {name}: not found ({err})")
    if "preview" in wanted:
        displays.append(PreviewDisplay(args.preview_path))
        print(f"[TOK] preview: writing {args.preview_path}")
    return displays


def main():
    p = argparse.ArgumentParser(description="Show TOK token predictions on Pi screens.")
    p.add_argument("--url", default="http://localhost:5000/api/usage")
    p.add_argument("--interval", type=float, default=5.0, help="seconds between polls")
    p.add_argument("--display", action="append", choices=["auto", "oled", "lcd", "preview", "console"],
                   help="repeatable; default auto = every screen that responds")
    p.add_argument("--i2c-bus", type=int, default=1)
    p.add_argument("--oled-addr", type=lambda x: int(x, 0), default=0x3C)
    p.add_argument("--oled-driver", choices=["ssd1306", "sh1106"], default="ssd1306")
    p.add_argument("--preview-path", default=str(Path(__file__).with_name("preview.png")))
    args = p.parse_args()

    displays = build_displays(args)
    state = State()
    threading.Thread(target=poll, args=(args.url, args.interval, state), daemon=True).start()

    try:
        while True:
            now = time.monotonic()
            for disp in displays:
                try:
                    disp.show(state, now)
                except Exception as err:
                    print(f"[TOK] {type(disp).__name__} error: {err}")
            time.sleep(1 / FPS)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
