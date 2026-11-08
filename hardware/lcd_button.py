"""TOK on a Grove 16x2 RGB LCD, with a Grove button as power + "Refresh Usage".

    Line 1: predicted token usage      e.g.  25,316 tok   51%
    Line 2: a session comment or the live draft label

Button:
    press while off  -> turn on and fetch the first prediction
    tap while on     -> refresh the current mode
    double tap       -> reset usage and show the new session total
    touch sensor     -> switch between session total and live draft
    hold 2 seconds   -> turn off (screen and backlight dark)

The backlight colour follows the same levels as the web interface.

An attached SSD1306 OLED shows the mascot and the same count as the LCD.
Both displays go dark when TOK is turned off.

Wiring (Grove Base HAT): LCD -> any I2C port, button -> D5.
Run on the Pi:  python lcd_button.py
Use --live to start in live draft mode.
"""
import argparse
import threading
import time
from urllib.parse import urlsplit

from gpiozero import Button
from smbus2 import SMBus

import tok_display as tok  # shared with simulator.py: what to show, Gemini comments, colours
from button_gestures import ButtonGestures

# Optional 0.96" OLED on the same I2C bus (mascot + number). The button below
# refreshes it too; if no OLED is attached the script just runs LCD-only.
try:
    import display as oled_mod
except ImportError:
    oled_mod = None

LCD_ADDR = 0x3E
RGB_ADDR = 0x62
BUTTON_PIN = 5  # Base HAT D5
TOUCH_PIN = 22  # Grove touch sensor on Base HAT D22 (HIGH while touched)
HOLD_S = 2  # hold the button this long to turn TOK off
DOUBLE_TAP_S = 0.35  # time from the first release to the next press
LIVE_REFRESH_S = 0.5

# The LCD currently on the Pi has a dead blue channel, so mood colours are
# remapped to red/green only. Set to False once you have a working LCD.
BROKEN_BLUE = True
BROKEN_BLUE_PALETTE = {
    "over": (255, 0, 0),
    "high": (255, 70, 0),
    "mid": (200, 150, 0),
    "low": (0, 200, 0),
}
IDLE_RGB = (0, 90, 0) if BROKEN_BLUE else tok.IDLE_RGB

bus = SMBus(1)
button = Button(BUTTON_PIN, pull_up=False, bounce_time=0.025)  # Grove button is HIGH when pressed


# ---------- LCD ----------
_lcd_warned = False


def lcd_safe(fn):
    """A missing/loose LCD must not kill the script: the OLED and button keep working."""
    def wrapper(*args, **kwargs):
        global _lcd_warned
        try:
            return fn(*args, **kwargs)
        except OSError as error:
            if not _lcd_warned:
                print(f"LCD not responding ({error}); check its cable. Carrying on without it.", flush=True)
                _lcd_warned = True
    return wrapper


@lcd_safe
def command(value):
    bus.write_byte_data(LCD_ADDR, 0x80, value)


def lcd_init():
    time.sleep(0.1)
    # ST7032-style init incl. contrast: some Grove LCDs show nothing without it.
    for value in (0x38, 0x39, 0x14, 0x78, 0x56, 0x6C):
        command(value)
        time.sleep(0.01)
    time.sleep(0.25)
    for value in (0x38, 0x0C, 0x01):  # normal set, display on, clear
        command(value)
        time.sleep(0.05)
    command(0x06)


@lcd_safe
def set_rgb(rgb):
    red, green, blue = rgb
    bus.write_byte_data(RGB_ADDR, 0x00, 0)
    bus.write_byte_data(RGB_ADDR, 0x01, 0)
    bus.write_byte_data(RGB_ADDR, 0x08, 0xAA)
    bus.write_byte_data(RGB_ADDR, 0x04, red)
    bus.write_byte_data(RGB_ADDR, 0x03, green)
    bus.write_byte_data(RGB_ADDR, 0x02, blue)


@lcd_safe
def display(line1, line2):
    # Same sequence as the proven test script: clear + re-init before every write.
    command(0x01)
    time.sleep(0.05)
    command(0x0C)
    command(0x28)
    for row, text in enumerate([line1, line2]):
        command(0x80 if row == 0 else 0xC0)
        for char in text.ljust(16)[:16]:
            bus.write_byte_data(LCD_ADDR, 0x40, ord(char))


# ---------- refresh ----------
last_line1 = "TOK"
last_live_usage = None
powered = False
oled = None
oled_state = None
if oled_mod:
    try:
        oled = oled_mod.OledDisplay(1, 0x3C, "ssd1306")
        oled_state = oled_mod.State()
        print("OLED ready", flush=True)
    except Exception as error:  # no OLED attached: LCD-only
        print(f"No OLED ({error})", flush=True)


def oled_loop():
    """Redraw the OLED ~8x/s so the mascot animates; blank while TOK is off."""
    was_on = False
    while True:
        try:
            if powered:
                oled.show(oled_state, time.monotonic())
                was_on = True
            elif was_on:
                oled.device.clear()
                was_on = False
        except Exception as error:
            print(f"OLED error: {error}", flush=True)
        time.sleep(1 / oled_mod.FPS)


def backlight_for(frame):
    """The frame's mood colour, adjusted for this particular LCD."""
    return BROKEN_BLUE_PALETTE[frame.level] if BROKEN_BLUE else frame.rgb


def refresh():
    global last_line1
    print("Refreshing TOK...", flush=True)
    set_rgb(tok.BUSY_RGB)
    display(last_line1, "Refreshing...")

    frame = tok.refresh_frame()
    if frame.source.startswith("error"):
        display(last_line1, frame.line2)
        set_rgb(tok.ERROR_RGB)
        if oled_state:
            oled_state.status, oled_state.error = "error", frame.source
        print(f"Error: {frame.source}", flush=True)
        return

    frame.line1 = tok.usage_line(frame.tokens, frame.scale, unit="total")
    show_frame(frame, "Session total")
    print(f"{frame.line1} | {frame.line2} ({frame.source})", flush=True)


def reset_usage():
    set_rgb(tok.BUSY_RGB)
    display(last_line1, "Resetting...")
    try:
        tokens, scale = tok.reset_usage()
    except (OSError, ValueError) as error:
        display(last_line1, "Reset failed")
        set_rgb(tok.ERROR_RGB)
        if oled_state:
            oled_state.status, oled_state.error = "error", "Reset failed"
        print(f"Usage reset failed: {error}", flush=True)
        return False

    _, level, rgb, _ = tok.level_for(tokens, scale)
    frame = tok.Frame(tok.usage_line(tokens, scale, unit="total"), "Usage reset", rgb, "reset",
                      level, tokens, scale)
    show_frame(frame, "Session total")
    return True


def show_frame(frame, mode_label):
    global last_line1
    last_line1 = frame.line1
    if oled_state:
        if frame.tokens != oled_state.tokens:
            oled_state.changed_at = time.monotonic()  # makes the mascot celebrate
        oled_state.tokens, oled_state.scale, oled_state.status = frame.tokens, frame.scale, "ok"
        oled_state.token_label = mode_label
    display(frame.line1, frame.line2)
    set_rgb(backlight_for(frame))


def refresh_live(url):
    global last_live_usage
    try:
        usage = tok.fetch_usage(url, timeout=2)
    except (OSError, ValueError) as error:
        if last_live_usage != "error":
            print(f"Live draft fetch failed: {error}", flush=True)
            display(last_line1, "Refresh failed")
            set_rgb(tok.ERROR_RGB)
            if oled_state:
                oled_state.status, oled_state.error = "error", "Refresh failed"
        last_live_usage = "error"
        return
    if usage == last_live_usage:
        return
    tokens, scale = usage
    _, level, rgb, _ = tok.level_for(tokens, scale)
    frame = tok.Frame(tok.usage_line(tokens, scale), "Live draft", rgb, "live", level, tokens, scale)
    show_frame(frame, "Live draft")
    print(f"Live draft: {tokens}/{scale}", flush=True)
    last_live_usage = usage


def power_on(refresh_display):
    global last_line1, last_live_usage, powered
    print("TOK on", flush=True)
    last_line1 = "TOK"
    last_live_usage = None
    powered = True
    if oled_state:
        oled_state.tokens, oled_state.status = None, "loading"
    set_rgb(IDLE_RGB)
    display("TOK", "Starting up...")
    time.sleep(0.6)
    refresh_display()


def power_off():
    global powered
    print("TOK off", flush=True)
    powered = False
    display("TOK", "Bye! Press=on")
    time.sleep(1)
    command(0x08)  # display off
    set_rgb((0, 0, 0))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Show Tok usage on the LCD")
    parser.add_argument("--live", action="store_true", help="Start in live draft mode")
    args = parser.parse_args()
    live_mode = args.live
    live_url = urlsplit(tok.API_URL)._replace(path="/api/draft", query="", fragment="").geturl()

    def refresh_display():
        if live_mode:
            refresh_live(live_url)
        else:
            refresh()

    try:
        lcd_init()
        display("TOK", "Press to start")
        set_rgb(IDLE_RGB)
        on = False
        gestures = ButtonGestures(HOLD_S, DOUBLE_TAP_S)
        button.when_pressed = lambda: gestures.record(True)
        button.when_released = lambda: gestures.record(False)
        try:
            touch = Button(TOUCH_PIN, pull_up=False, bounce_time=0.05)
            touch.when_pressed = gestures.touch
        except Exception as error:  # sensor not attached: the button still works
            print(f"Touch sensor unavailable ({error})", flush=True)
        if oled:
            threading.Thread(target=oled_loop, daemon=True).start()

        while True:
            gesture = gestures.read(
                timeout=LIVE_REFRESH_S if on and live_mode else None,
                allow_double_tap=on,
            )
            if not on:
                if gesture == "touch":
                    continue  # touching does not power TOK on
                power_on(refresh_display)
                on = True
            elif gesture == "hold":
                power_off()
                on = False
            elif gesture == "double_tap":
                if reset_usage():
                    live_mode = False
                else:
                    last_live_usage = None
            else:
                if gesture == "touch":
                    live_mode = not live_mode
                    print(f"Touch -> {'live draft' if live_mode else 'session total'}", flush=True)
                    last_live_usage = None
                    last_line1 = "TOK"
                    if oled_state:
                        oled_state.tokens, oled_state.status = None, "loading"
                    display(last_line1, "Live draft" if live_mode else "Session total")
                refresh_display()

    except KeyboardInterrupt:
        display("TOK", "Goodbye!")
    finally:
        button.close()
        bus.close()
