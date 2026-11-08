"""Browser simulator for the TOK 16x2 RGB LCD + button. No Raspberry Pi needed.

    1. start the web app:   cd interface && python app.py        (port 5000)
    2. start this:          python hardware/simulator.py         (port 5001)
    3. open http://127.0.0.1:5001 and press the button (or hit Space)

It uses the same tok_display.py as the real hardware script, so what you see
here is what the working LCD will show. Put GEMINI_API_KEY in hardware/.env
to get Gemini-written comments; without it you get the canned ones.
"""
import os

from flask import Flask, jsonify, render_template_string

import tok_display

app = Flask(__name__)

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TOK LCD simulator</title>
<style>
  body { margin: 0; min-height: 100vh; display: grid; place-items: center;
         background: #14101f; color: #cbb8ff; font: 14px system-ui, sans-serif; }
  main { display: grid; gap: 22px; justify-items: center; padding: 16px; }
  .board { background: #1d1730; padding: 22px; border-radius: 14px;
           border: 1px solid #3a2d63; }
  .lcd { --bl: rgb(110,40,180); background: var(--bl); padding: 16px 18px;
         border-radius: 6px; box-shadow: 0 0 40px -6px var(--bl), inset 0 0 0 3px #0003;
         transition: background .35s, box-shadow .35s; }
  .rows { background: #0003; padding: 10px 12px; border-radius: 3px;
          font: 700 clamp(15px, 4.6vw, 28px)/1.5 ui-monospace, Menlo, Consolas, monospace;
          letter-spacing: .08em; white-space: pre; color: #111;
          text-shadow: 0 0 1px #0006; }
  .rows span { display: block; }
  button { all: unset; cursor: pointer; width: 84px; height: 84px; border-radius: 50%;
           background: #8b5cf6; color: #fff; text-align: center; line-height: 84px;
           font-weight: 700; box-shadow: 0 6px 0 #4c2d99; transition: transform .06s, box-shadow .06s; }
  button:active, button.down { transform: translateY(5px); box-shadow: 0 1px 0 #4c2d99; }
  .meta { font-size: 12px; opacity: .7; min-height: 1.4em; text-align: center; }
</style>
<main>
  <div class="board"><div class="lcd" id="lcd"><div class="rows">
    <span id="l1">TOK</span><span id="l2">Press to refresh</span>
  </div></div></div>
  <button id="btn" aria-label="Refresh usage">PRESS</button>
  <div class="meta" id="meta">Space or click to refresh</div>
</main>
<script>
  const $ = id => document.getElementById(id);
  const pad = s => (s + " ".repeat(16)).slice(0, 16);
  const SRC = {gemini: "comment by Gemini", canned: "canned comment (no Gemini key or it failed)"};
  let busy = false;
  async function press() {
    if (busy) return; busy = true;
    $("btn").classList.add("down");
    $("lcd").style.setProperty("--bl", "rgb(180,120,0)");
    $("l2").textContent = pad("Refreshing...");
    try {
      const f = await (await fetch("/press", {method: "POST"})).json();
      $("l1").textContent = pad(f.line1);
      $("l2").textContent = pad(f.line2);
      $("lcd").style.setProperty("--bl", `rgb(${f.rgb.join(",")})`);
      $("meta").textContent = SRC[f.source] || f.source;
    } catch (e) {
      $("l2").textContent = pad("Refresh failed");
      $("lcd").style.setProperty("--bl", "rgb(220,20,30)");
      $("meta").textContent = String(e);
    }
    setTimeout(() => $("btn").classList.remove("down"), 120);
    busy = false;
  }
  $("btn").addEventListener("click", press);
  addEventListener("keydown", e => { if (e.code === "Space") { e.preventDefault(); press(); } });
</script>
"""


@app.get("/")
def index():
    return render_template_string(PAGE)


@app.post("/press")
def press():
    frame = tok_display.refresh_frame()
    print(f"{frame.line1} | {frame.line2} | {frame.rgb} | {frame.source}")
    return jsonify(line1=frame.line1, line2=frame.line2, rgb=frame.rgb, source=frame.source)


if __name__ == "__main__":
    has_key = bool(os.environ.get("GEMINI_API_KEY"))
    print(f"Gemini comments: {'ON (' + tok_display.GEMINI_MODEL + ')' if has_key else 'off - using canned comments'}")
    print(f"Usage API: {tok_display.API_URL}")
    app.run(port=5001)
