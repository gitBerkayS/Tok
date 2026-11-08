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
const LIVE_REFRESH_MS = 500;
const SESSION_REFRESH_MS = 3000;
const FETCH_TIMEOUT_MS = 5000;
const history = [];

let shown = 0;
let animation = 0;
let settleTimer = 0;
let lastLevel = "low";
let lastTokens = null; // null until the first successful response
let lastScale = null;
let reading = "session";
let powered = true;
let pending = null;
let pollTimer;
let resetting = false;
let resetFailed = false;

const resetBtn = document.getElementById("reset");
const powerBtn = document.getElementById("power");
const resetDialog = document.getElementById("reset-dialog");
const resetForm = document.getElementById("reset-form");
const resetKey = document.getElementById("reset-key");
const readingButtons = document.querySelectorAll("[data-reading]");
const draftStatus = {
  ready: "Live draft", inactive: "No active composer",
  unavailable: "Composer unavailable", stale: "Collector stale",
};

const fmt = (n) => Math.round(n).toLocaleString("en-US");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- count-up / count-down ----------
function animateCount(target) {
  const id = ++animation;
  const from = shown;
  const start = performance.now();
  const duration = reading === "draft" ? 250 : 900;
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
  if (!history.length) {
    sparkLine.removeAttribute("points");
    sparkArea.removeAttribute("d");
    sparkDot.setAttribute("r", 0);
    return;
  }
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

  // A drop in the session total starts a new graph. Draft edits can go either way.
  if (reading === "session" && lastTokens !== null && tokens < lastTokens) history.length = 0;
  if (tokens !== lastTokens) history.push(tokens);
  lastTokens = tokens;
  lastScale = scale;
  if (history.length > HISTORY_MAX) history.shift();
  drawHistory();
}

function clearReading() {
  lastTokens = lastScale = null;
  lastLevel = card.dataset.level = "low";
  history.length = 0;
  drawHistory();
  animation++;
  shown = 0;
  countEl.textContent = percentEl.textContent = "—";
  fillEl.style.width = "0%";
  barEl.removeAttribute("aria-valuenow");
  scaleEl.textContent = fmt(Number(card.dataset.scale)) + " token reference scale";
}

async function fetchReading(path, controller, options) {
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(path, { ...options, cache: "no-store", signal: controller.signal });
    const data = await response.json();
    if (!response.ok) throw new Error(data?.error || "Server returned " + response.status);
    if (!Number.isSafeInteger(data?.tokens) || data.tokens < 0 ||
        !Number.isSafeInteger(data.scale) || data.scale <= 0 ||
        (path === "/api/draft" && !Object.hasOwn(draftStatus, data.status))) {
      throw new Error("Unexpected response");
    }
    return data;
  } catch (err) {
    if (err.name === "AbortError") throw new Error("Request timed out");
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

function syncControls() {
  for (const button of readingButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.reading === reading));
    button.disabled = !powered || resetting;
  }
  document.getElementById("reading-label").textContent = reading === "draft" ? "Live draft" : "Session total";
  document.getElementById("history-label").textContent = reading === "draft" ? "Draft history" : "Session history";
  powerBtn.textContent = powered ? "Turn display off" : "Turn display on";
  powerBtn.disabled = resetting;
  refreshBtn.hidden = resetBtn.hidden = !powered;
  refreshBtn.disabled = resetting;
  resetBtn.disabled = resetting;
}

function stopReading() {
  clearTimeout(pollTimer);
  const controller = pending;
  pending = null;
  controller?.abort();
}

function showReading(data, message, celebrate) {
  if (!resetFailed) errorEl.hidden = true;
  if (data.tokens !== lastTokens || data.scale !== lastScale) render(data);
  const face = FACE_FOR_LEVEL[lastLevel];
  if (card.dataset.state === "result" && statusEl.textContent === message && !celebrate) return;
  clearTimeout(settleTimer);
  setStatus(celebrate ? "result" : "idle", celebrate ? "celebrate" : face, message);
  if (celebrate) settleTimer = setTimeout(() => setStatus("idle", face, message), 1700);
}

function showError(prefix, err) {
  clearTimeout(settleTimer);
  setStatus("error", "error", prefix);
  errorEl.textContent = prefix + ". " + err.message;
  errorEl.hidden = false;
}

function queueReading() {
  if (powered && !resetting && !document.hidden) {
    const delay = reading === "draft" ? LIVE_REFRESH_MS : SESSION_REFRESH_MS;
    pollTimer = setTimeout(() => loadReading(false), delay);
  }
}

async function loadReading(manual = true) {
  if (!powered || resetting) return;
  stopReading();
  const controller = pending = new AbortController();
  const draft = reading === "draft";
  if (manual) {
    resetFailed = false;
    clearTimeout(settleTimer);
    errorEl.hidden = true;
    setStatus("loading", "loading", "Refreshing…");
  }
  try {
    const [data] = await Promise.all([
      fetchReading(draft ? "/api/draft" : "/api/usage", controller),
      manual ? sleep(MIN_LOADING_MS) : null,
    ]);
    if (pending !== controller) return;
    // A background session check only updates the display when the total changes
    // or when recovering from a request error.
    if (!draft && !manual && data.tokens === lastTokens && data.scale === lastScale &&
        (card.dataset.state === "idle" || card.dataset.state === "result" || resetFailed)) return;
    const message = draft ? draftStatus[data.status] :
      "Updated " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    showReading(data, message, (!draft || data.status === "ready") && data.tokens !== lastTokens);
  } catch (err) {
    if (pending === controller) showError("Refresh failed", err);
  } finally {
    if (pending === controller) {
      pending = null;
      queueReading();
    }
  }
}

for (const button of readingButtons) {
  button.addEventListener("click", () => {
    if (reading === button.dataset.reading) return;
    reading = button.dataset.reading;
    clearReading();
    syncControls();
    loadReading();
  });
}

powerBtn.addEventListener("click", () => {
  powered = !powered;
  syncControls();
  if (powered) loadReading();
  else {
    stopReading();
    clearTimeout(settleTimer);
    clearReading();
    errorEl.hidden = true;
    setStatus("off", "calm", "Display off");
  }
});

resetBtn.addEventListener("click", () => resetDialog.showModal());
document.getElementById("cancel-reset").addEventListener("click", () => resetDialog.close());
resetDialog.addEventListener("close", () => resetForm.reset());
resetForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const key = resetKey.value;
  resetDialog.close();
  resetForm.reset();
  stopReading();
  clearTimeout(settleTimer);
  resetting = true;
  resetFailed = false;
  syncControls();
  errorEl.hidden = true;
  setStatus("loading", "loading", "Resetting…");
  try {
    const data = await fetchReading("/api/usage/reset", new AbortController(), {
      method: "POST", headers: { Authorization: "Bearer " + key },
    });
    if (data.tokens !== 0) throw new Error("Unexpected reset response");
    reading = "session";
    clearReading();
    showReading(data, "Usage reset", true);
  } catch (err) {
    resetFailed = true;
    showError("Reset failed", err);
  } finally {
    resetting = false;
    syncControls();
    resetBtn.focus();
    queueReading();
  }
});

// ---------- display mode ----------
function setMode(mode) {
  card.dataset.mode = mode;
  document.querySelectorAll(".mode[data-mode]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.mode === mode))
  );
  try { localStorage.setItem("tok-mode", mode); } catch (e) { /* storage unavailable */ }
}

document.querySelectorAll(".mode[data-mode]").forEach((b) =>
  b.addEventListener("click", () => setMode(b.dataset.mode))
);
// ?mode=dashboard in the URL wins, so a demo link can open straight into a mode.
let saved = new URLSearchParams(location.search).get("mode");
try { saved = saved || localStorage.getItem("tok-mode"); } catch (e) { /* storage unavailable */ }
if (saved === "mascot" || saved === "dashboard") setMode(saved);

refreshBtn.addEventListener("click", () => loadReading());
syncControls();
loadReading();
document.addEventListener("visibilitychange", () => {
  if (!powered || resetting) return;
  if (document.hidden) stopReading();
  else loadReading(false);
});
