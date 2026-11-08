#!/usr/bin/env bash
# Start TOK on the Pi: Flask API + the button/LCD/OLED script. Safe to re-run (restarts both).
#   ~/TOK/hardware/start.sh     (stop with ./stop.sh)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/hardware/stop.sh"

nohup "$ROOT/.venv/bin/python" "$ROOT/interface/app.py" > "$ROOT/flask.log" 2>&1 &
for _ in $(seq 1 20); do   # wait for Flask to answer before the button script needs it
    curl -sf http://127.0.0.1:5000/api/usage > /dev/null && break
    sleep 0.5
done
nohup "$ROOT/.venv/bin/python" -u "$ROOT/hardware/lcd_button.py" > "$ROOT/lcd.log" 2>&1 &
echo "TOK started. Press the button to turn it on. Logs: $ROOT/flask.log $ROOT/lcd.log"
