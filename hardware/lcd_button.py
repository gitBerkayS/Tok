"""TOK on a Grove 16x2 RGB LCD, with a Grove button as "Refresh Usage".

    Line 1: predicted token usage      e.g.  25,316 tok   51%
    Line 2: a short comment on it      e.g.  Nice and steady (Gemini-written when GEMINI_API_KEY is set)

The backlight colour follows the same levels as the web interface.

Wiring (Grove Base HAT): LCD -> any I2C port, button -> D5.
Run on the Pi:  python lcd_button.py
"""
import time

from gpiozero import Button
from smbus2 import SMBus

import tok_display as tok  # shared with simulator.py: what to show, Gemini comments, colours

LCD_ADDR = 0x3E
RGB_ADDR = 0x62
BUTTON_PIN = 5  # Base HAT D5

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


def set_rgb(rgb):
    red, green, blue = rgb
    bus.write_byte_data(RGB_ADDR, 0x00, 0)
    bus.write_byte_data(RGB_ADDR, 0x01, 0)
    bus.write_byte_data(RGB_ADDR, 0x08, 0xAA)
    bus.write_byte_data(RGB_ADDR, 0x04, red)
    bus.write_byte_data(RGB_ADDR, 0x03, green)
    bus.write_byte_data(RGB_ADDR, 0x02, blue)


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
        print(f"Error: {frame.source}", flush=True)
        return

    last_line1 = frame.line1
    display(frame.line1, frame.line2)
    set_rgb(backlight_for(frame))
    print(f"{frame.line1} | {frame.line2} ({frame.source})", flush=True)


if __name__ == "__main__":
    try:
        lcd_init()
        display("TOK", "Press to refresh")
        set_rgb(IDLE_RGB)

        while True:
            button.wait_for_press()
            refresh()
            button.wait_for_release()

    except KeyboardInterrupt:
        display("TOK", "Goodbye!")
    finally:
        bus.close()
