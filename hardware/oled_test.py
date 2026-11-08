"""Quick check that the 0.96" SSD1306 OLED works.   python oled_test.py [--driver sh1106]

Shows a border, text and a moving bar for ~8 seconds, then clears.
"""
import argparse
import time

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled import device

parser = argparse.ArgumentParser()
parser.add_argument("--driver", default="ssd1306", choices=["ssd1306", "sh1106"])
parser.add_argument("--addr", type=lambda x: int(x, 0), default=0x3C)
args = parser.parse_args()

oled = getattr(device, args.driver)(i2c(port=1, address=args.addr))  # 128x64

for step in range(33):
    with canvas(oled) as draw:
        draw.rectangle(oled.bounding_box, outline="white")
        draw.text((10, 6), "TOK OLED OK", fill="white")
        draw.text((10, 20), f"{args.driver} @ {hex(args.addr)}", fill="white")
        draw.rectangle((10, 44, 10 + step * 3, 54), fill="white")
    time.sleep(0.25)

oled.clear()
print("done")
