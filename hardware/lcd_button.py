"""TOK on a Grove 16x2 RGB LCD, with a Grove button as power + "Refresh Usage".

    Line 1: predicted token usage      e.g.  25,316 tok   51%
    Line 2: a short comment on it      e.g.  Nice and steady (Gemini-written when GEMINI_API_KEY is set)

Button:
    press while off  -> turn on and fetch the first prediction
    press while on   -> refresh (each refresh is one GET /api/usage = one model run)
    hold 2 seconds   -> turn off (screen and backlight dark)

The backlight colour follows the same levels as the web interface.

If a 0.96" OLED (SSD1306 @ 0x3C) is attached, the same button drives it too: it shows the
mascot + number only after a press (no polling), and goes dark when TOK is turned off.

Wiring (Grove Base HAT): LCD -> any I2C port, button -> D5.
Run on the Pi:  python lcd_button.py
"""
import threading
import time

from gpiozero import Button
from smbus2 import SMBus

import tok_display as tok  # shared with simulator.py: what to show, Gemini comments, colours

# Optional 0.96" OLED on the same I2C bus (mascot + number). The button below
# refreshes it too; if no OLED is attached the script just runs LCD-only.
try:
    import display as oled_mod
except ImportError:
    oled_mod = None

LCD_ADDR = 0x3E
RGB_ADDR = 0x62
BUTTON_PIN = 5  # Base HAT D5
HOLD_S = 2  # hold the button this long to turn TOK off

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
button = Button(BUTTON_PIN, pull_up=False, bounce_time=0.1)  # Grove button is HIGH when pressed


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

    last_line1 = frame.line1
    if oled_state:
        if frame.tokens != oled_state.tokens:
            oled_state.changed_at = time.monotonic()  # makes the mascot celebrate
        oled_state.tokens, oled_state.scale, oled_state.status = frame.tokens, frame.scale, "ok"
    display(frame.line1, frame.line2)
    set_rgb(backlight_for(frame))
    print(f"{frame.line1} | {frame.line2} ({frame.source})", flush=True)


def power_on():
    global last_line1, powered
    print("TOK on", flush=True)
    last_line1 = "TOK"
    powered = True
    if oled_state:
        oled_state.tokens, oled_state.status = None, "loading"  # mascot waits for the first reading
    set_rgb(IDLE_RGB)
    display("TOK", "Starting up...")
    time.sleep(0.6)
    refresh()


def power_off():
    global powered
    print("TOK off", flush=True)
    powered = False
    display("TOK", "Bye! Press=on")
    time.sleep(1)
    command(0x08)  # display off
    set_rgb((0, 0, 0))


if __name__ == "__main__":
    try:
        lcd_init()
        display("TOK", "Press to start")
        set_rgb(IDLE_RGB)
        on = False
        if oled:
            threading.Thread(target=oled_loop, daemon=True).start()

        while True:
            button.wait_for_press()
            button.wait_for_release(timeout=HOLD_S)
            held = button.is_pressed  # still down after HOLD_S -> long press

            if not on:
                power_on()
                on = True
            elif held:
                power_off()
                on = False
            else:
                refresh()

            button.wait_for_release()

    except KeyboardInterrupt:
        display("TOK", "Goodbye!")
    finally:
        bus.close()
