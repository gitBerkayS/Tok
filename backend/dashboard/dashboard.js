// Refresh and render capture features, recent CSV rows, and session totals.
const fields = [
  ["chars", "Characters"], ["words", "Words"], ["avg_chars_per_word", "Avg. word length"],
  ["punctuation_ratio", "Punctuation"], ["symbol_ratio", "Symbols"],
  ["longest_word_chars", "Longest word"], ["vocab_size", "Vocabulary size"]
];
const labels = { safari: "Safari", chrome: "Chrome", chatgpt: "ChatGPT app", codex: "Codex" };
const statuses = { ready: "Capturing", inactive: "Inactive", unavailable: "Composer unavailable", stale: "Collector stale", offline: "Backend offline" };
const byId = id => document.getElementById(id);
const values = fields.map(([, label]) => {
  const card = document.createElement("div");
  const title = document.createElement("dt");
  const value = document.createElement("dd");
  title.textContent = label;
  value.textContent = "—";
  card.append(title, value);
  byId("metrics").append(card);
  return value;
});
const format = (key, value) => value == null ? "—" :
  key.endsWith("_ratio") ? (value * 100).toFixed(1) + "%" :
  value.toLocaleString(undefined, { maximumFractionDigits: 2 });
const setStatus = status => {
  byId("status").textContent = statuses[status] ?? status;
  byId("status").dataset.status = status;
};

let lastRow = null;
function render(data) {
  const current = data.current;
  const latest = current.features ? current : data.recent[0];
  const session = data.session;
  byId("session-total").textContent = session?.tracking_enabled ?
    session.inferred_submissions.toLocaleString() + " inferred submissions · " +
    session.submitted_chars.toLocaleString() + " submitted characters" : "Submission tracking is off";
  setStatus(current.status);
  byId("source").textContent = latest ?
    (current.features ? "Live · " : "Last saved · ") + (labels[latest.source] ?? "Unknown source") : "";
  values.forEach((value, index) => {
    const key = fields[index][0];
    value.textContent = format(key, latest?.features[key]);
  });
  byId("hint").textContent = current.status === "ready" ? "Updates as the draft changes. Only numeric features are shown." :
    "Keep this page in a separate window and focus the ChatGPT composer to resume capture.";
  byId("count").textContent = data.rows_written.toLocaleString() + (data.rows_written === 1 ? " row saved" : " rows saved");

  const historyKey = JSON.stringify([data.rows_written, data.recent[0]?.updated_at]);
  if (historyKey === lastRow) return;
  lastRow = historyKey;
  const history = byId("history");
  history.replaceChildren();
  if (!data.recent.length) {
    const cell = history.insertRow().insertCell();
    cell.colSpan = 9;
    cell.textContent = "No rows saved yet.";
    cell.className = "muted";
  }
  for (const entry of data.recent) {
    const row = history.insertRow();
    const cells = [new Date(entry.updated_at).toLocaleTimeString(), labels[entry.source] ?? "Unknown",
      ...fields.map(([key]) => format(key, entry.features[key]))];
    for (const value of cells) row.insertCell().textContent = value;
  }
}

async function refresh() {
  try {
    const response = await fetch("/dashboard-data", { cache: "no-store", signal: AbortSignal.timeout(2500) });
    if (!response.ok) throw new Error("Dashboard request failed");
    render(await response.json());
  } catch {
    setStatus("offline");
    byId("source").textContent = lastRow === null ? "" : "Previous reading";
    byId("hint").textContent = "Trying to reconnect to the local backend.";
  } finally {
    setTimeout(refresh, 500);
  }
}
refresh();
