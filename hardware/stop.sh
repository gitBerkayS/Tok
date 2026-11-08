#!/usr/bin/env bash
# Stop the TOK processes (the Pi stays on). Hold the button 2s first if you want the screens dark.
pkill -f "TOK/hardware/lcd_button.py"
pkill -f "TOK/interface/app.py"
exit 0
