const card = document.querySelector(".card");
const mascot = document.getElementById("mascot");
const countEl = document.getElementById("token-count");
const percentEl = document.getElementById("percent");
const fillEl = document.getElementById("fill");
const barEl = document.getElementById("bar");
const scaleEl = document.getElementById("scale-label");
const statusEl = document.getElementById("status-text");
const errorEl = document.getElementById("error");
const refreshBtn = document.getElementById("refresh");
const historyCountEl = document.getElementById("history-count");
const sparkLine = document.getElementById("spark-line");
const sparkArea = document.getElementById("spark-area");
const sparkDot = document.getElementById("spark-dot");

const HISTORY_MAX = 20;
const MIN_LOADING_MS = 450; // keep the "thinking" state visible on fast local requests
const history = [];

let shown = 0;
let animation = 0;
let settleTimer = 0;
let lastLevel = "low";

const fmt = (n) => Math.round(n).toLocaleString("en-US");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- count-up / count-down ----------
function animateCount(target) {
  const id = ++animation;
  const from = shown;
  const start = performance.now();
  const duration = 900;
  function tick(now) {
    if (id !== animation) return; // a newer result took over
    const t = Math.min(Math.max((now - start) / duration, 0), 1);
    shown = from + (target - from) * (1 - Math.pow(1 - t, 3));
    countEl.textContent = fmt(shown);
    if (t < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

// ---------- state helpers ----------
function levelFor(ratio) {
  if (ratio >= 1) return "over";
  if (ratio >= 0.75) return "high";
  if (ratio >= 0.4) return "mid";
  return "low";
}
const FACE_FOR_LEVEL = { low: "calm", mid: "happy", high: "excited", over: "maxed" };

function setStatus(state, face, text) {
  card.dataset.state = state;
  mascot.dataset.face = face;
  statusEl.textContent = text;
}

// ---------- history sparkline ----------
function drawHistory() {
  historyCountEl.textContent = history.length ? "last " + history.length : "";
  if (!history.length) return;
  const W = 300, H = 64, PAD = 6;
  const max = Math.max(...history) * 1.1 || 1;
  const pts = history.map((v, i) => [
    history.length === 1 ? W / 2 : PAD + (i / (history.length - 1)) * (W - 2 * PAD),
    H - PAD - (v / max) * (H - 2 * PAD),
  ]);
  const line = pts.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  sparkLine.setAttribute("points", line);
  const first = pts[0], last = pts[pts.length - 1];
  sparkArea.setAttribute(
    "d",
    "M" + first[0] + "," + H + " L" + line.replace(/ /g, " L") + " L" + last[0] + "," + H + " Z"
  );
  sparkDot.setAttribute("cx", last[0]);
  sparkDot.setAttribute("cy", last[1]);
  sparkDot.setAttribute("r", 3.5);
}

// ---------- render a new prediction ----------
function render({ tokens, scale }) {
  const ratio = tokens / scale;
  lastLevel = levelFor(ratio);
  card.dataset.level = lastLevel;

  animateCount(tokens);
  fillEl.style.width = Math.min(ratio * 100, 100) + "%";
  barEl.setAttribute("aria-valuenow", Math.min(ratio * 100, 100).toFixed(1));
  percentEl.textContent = (ratio * 100).toFixed(1) + "%";
  scaleEl.textContent = fmt(scale) + " token reference scale";

  history.push(tokens);
  if (history.length > HISTORY_MAX) history.shift();
  drawHistory();
}

function settle() {
  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  setStatus("idle", FACE_FOR_LEVEL[lastLevel], "Updated " + time);
}

// ---------- fetch ----------
async function loadUsage() {
  clearTimeout(settleTimer);
  refreshBtn.disabled = true;
  refreshBtn.textContent = "Refreshing…";
  errorEl.hidden = true;
  setStatus("loading", "loading", "Thinking…");

  try {
    const [res] = await Promise.all([fetch("/api/usage", { cache: "no-store" }), sleep(MIN_LOADING_MS)]);
    if (!res.ok) throw new Error("Server returned " + res.status);
    const data = await res.json();
    // Accept either {tokens, scale} or a bare number.
    const payload = typeof data === "number" ? { tokens: data } : data;
    const tokens = Number(payload.tokens);
    if (!Number.isFinite(tokens)) throw new Error("Unexpected response");

    render({
      tokens,
      scale: Number(payload.scale) || Number(card.dataset.scale) || 5000,
    });
    setStatus("result", "celebrate", "New result");
    settleTimer = setTimeout(settle, 1700);
  } catch (err) {
    setStatus("error", "error", "Connection error");
    errorEl.textContent = "Couldn't load usage. " + err.message;
    errorEl.hidden = false;
  } finally {
    refreshBtn.disabled = false;
    refreshBtn.textContent = "Refresh Usage";
  }
}

// ---------- display mode ----------
function setMode(mode) {
  card.dataset.mode = mode;
  document.querySelectorAll(".mode").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.mode === mode))
  );
  try { localStorage.setItem("tok-mode", mode); } catch (e) { /* storage unavailable */ }
}

document.querySelectorAll(".mode").forEach((b) =>
  b.addEventListener("click", () => setMode(b.dataset.mode))
);
// ?mode=dashboard in the URL wins, so a demo link can open straight into a mode.
let saved = new URLSearchParams(location.search).get("mode");
try { saved = saved || localStorage.getItem("tok-mode"); } catch (e) { /* storage unavailable */ }
if (saved === "mascot" || saved === "dashboard") setMode(saved);

refreshBtn.addEventListener("click", loadUsage);
loadUsage();
