#!/usr/bin/env bash
# Start TOK on the Pi. Use --live with TOK_API_URL to read drafts from the Mac.
#   ~/TOK/hardware/start.sh     (stop with ./stop.sh)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "${1:-}" == "--live" ]]; then
    if [[ "${TOK_API_URL:-}" != http*://*/api/usage ]]; then
        echo "Set TOK_API_URL to the Mac's http://HOST:5000/api/usage before using --live." >&2
        exit 1
    fi
    if ! curl -fsS --max-time 5 "${TOK_API_URL%/api/usage}/api/draft" > /dev/null; then
        echo "The Mac's live draft endpoint did not respond. The current display process is still running." >&2
        exit 1
    fi
    "$ROOT/hardware/stop.sh"
    nohup "$ROOT/.venv/bin/python" -u "$ROOT/hardware/lcd_button.py" --live > "$ROOT/lcd.log" 2>&1 &
    echo "TOK live display started. Press the button to turn it on. Log: $ROOT/lcd.log"
    exit 0
fi

"$ROOT/hardware/stop.sh"

nohup "$ROOT/.venv/bin/python" "$ROOT/interface/app.py" > "$ROOT/flask.log" 2>&1 &
for _ in $(seq 1 20); do   # wait for Flask to answer before the button script needs it
    curl -sf http://127.0.0.1:5000/api/usage > /dev/null && break
    sleep 0.5
done
nohup "$ROOT/.venv/bin/python" -u "$ROOT/hardware/lcd_button.py" > "$ROOT/lcd.log" 2>&1 &
echo "TOK started. Press the button to turn it on. Logs: $ROOT/flask.log $ROOT/lcd.log"
