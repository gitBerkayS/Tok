# Tok

Tok is a macOS hackathon prototype for measuring the prompts you write in ChatGPT and Codex. As you type in a supported composer, Tok converts the draft into numeric features and writes them to a local CSV. JetonCount estimates token usage from those features, and Tok can show the result in a web interface or on a Raspberry Pi display.

Prompt length is easy to see in characters, but token usage depends on how a model's tokenizer splits text. Tok gives the team a way to collect features from real editing sessions and hand them to JetonCount for token estimation. The demo shows live draft estimates and a separate session total for likely sends. API-equivalent cost estimates are planned.

## Run the live demo

You’ll need a Mac with Python 3.9 or later, the Swift compiler (`swiftc`), and Safari or Chrome. Run the commands from the repository root.

1. Start the backend in a terminal.

   ```sh
   python3 -B -m backend
   ```

   The backend prints the path to a fresh `prompt_features.<timestamp>.csv` and listens on `127.0.0.1:8765`.

2. Build and start the collector in a second terminal.

   ```sh
   swiftc capture/TokCapture.swift -o /tmp/tok-capture
   /tmp/tok-capture
   ```

   If macOS prompts for Accessibility access, enable it for the collector or the launcher shown in **System Settings → Privacy & Security → Accessibility**, then restart the collector.

3. In Safari or Chrome, open **chatgpt.com** and focus the prompt composer. Type a short prompt, pause, then edit it. Keep the browser in front while you type.

4. Check the session output. Each changed, nonempty draft adds a row, so a single prompt can produce several rows.

   ```sh
   curl -fsS http://127.0.0.1:8765/dashboard-data
   ```

   Look for `rows_written` and the recent feature rows. This endpoint is also useful after switching to Terminal, when the live reading may have cleared or gone stale. If no rows appear, restart the collector with `/tmp/tok-capture --probe` and focus the composer again. Probe mode reports Accessibility metadata without reading draft text.

### Try the backend with a synthetic prompt

Start a separate backend session with `python3 -B -m backend --csv /tmp/tok-demo.csv`. With the collector stopped, send a synthetic draft to the fresh backend.

```sh
curl -fsS -X PUT http://127.0.0.1:8765/draft \
  -H 'Content-Type: application/json' \
  -d '{"revision":1,"source":"chrome","status":"ready","draft":"Explain this function."}'
curl -fsS http://127.0.0.1:8765/reading
```

The backend accepts the draft and reports 22 characters and 3 words. Increment `revision` for each new request to the same session.

## Track likely sends

For this part of the demo, restart the backend with `python3 -B -m backend --track-submissions` and the collector with `/tmp/tok-capture --track-submissions`. If prompted, grant **Input Monitoring** and restart the collector.

Send a prompt with plain Enter or click ChatGPT’s Send button in Safari or Chrome. Tok uses the latest captured draft and waits up to 2.5 seconds for a verified empty composer. The backend creates a separate `submitted_features.<timestamp>.csv` at startup and appends one row per accepted send. Check the count and submitted character total with `curl -fsS http://127.0.0.1:8765/session`.

## How it works

The Swift collector watches the frontmost supported app through macOS Accessibility. It reads the focused composer after verifying the editor and, in browsers, the ChatGPT site. Accessibility notifications drive reads, with polling as a fallback. The Python backend receives snapshots over loopback, calculates features, skips duplicate refreshes, and writes the CSV.

Draft text passes from the collector to the backend on the same Mac. Tok stores numeric features in the CSVs and keeps draft text out of its logs and output files. The browser flow works without an extension.

### Other capture surfaces

| Surface | Setup |
| --- | --- |
| Codex for macOS | Run the collector with `--probe` and focus the message box. Set `TOK_CODEX_COMPOSER_ID` to the verified composer or editor container identifier before starting capture. |
| ChatGPT for macOS | Set `TOK_NATIVE_BUNDLE_ID` to the installed app's verified bundle identifier. Use `--probe` to identify the composer, then set `TOK_NATIVE_COMPOSER_ID` for capture. |
| Safari with an unlabeled editor | For a controlled demo, `--allow-unidentified-safari-editor` permits capture from a focused unlabeled text area on the verified ChatGPT site. Keep focus in the prompt composer because the flag can also match another unlabeled text area. |

The backend can serve an optional local preview at `/` when the Git-ignored `backend/dashboard.html` is present. The JSON endpoints work in a fresh checkout.

## CSV handoff

Both CSVs use the same seven columns in model input order.

```csv
chars,words,avg_chars_per_word,punctuation_ratio,symbol_ratio,longest_word_chars,vocab_size
```

Character counts use Unicode code points. Word counts use Python's Unicode word matches. Punctuation and symbol ratios divide by the total character count, and their character sets overlap. Start the backend with `--vocab-size N` when the target tokenizer's vocabulary size is known. Otherwise, the field is blank and should be filled before inference. Use the estimator below to run inference on the exported features. The [synthetic sample](examples/prompt_features.synthetic.csv) uses an illustrative vocabulary size.

## Estimate tokens from a capture CSV

From the repository root, run:

```sh
python3 -B -m backend --estimate-csv examples/prompt_features.synthetic.csv
```

The command reports the estimate and method for each row, plus their sum. Use a `submitted_features.*.csv` file for a session total because the draft CSV contains intermediate edits. The exporter and estimator use the exact seven-column header above. Every nonempty row supplies all seven raw values to the pinned JetonCount checkpoint. The estimator requires `torch`, `transformers`, and `safetensors`. Pass `--vocab-size` when starting capture to fill that column, or supply it during estimation to fill blank cells. Use the target tokenizer's confirmed vocabulary size. A nonpositive or nonfinite model prediction produces a result labeled `heuristic_fallback`.

The first cell in `JetonCount_Inference.ipynb` runs the same estimator from a notebook. Run that cell from the repository root and set the path to your capture CSV. The existing Databricks examples are separate cells that accept raw text.

With Flask installed, start the web interface and hardware API with the submissions CSV path.

```sh
env TOK_SUBMISSIONS_CSV=/path/to/submitted_features.csv python3 -m interface.app
```

Set `TOK_VOCAB_SIZE` if the CSV leaves the vocabulary size blank. With no CSV configured, the interface uses demo data.

## Reset the session on startup and serve the display

From the repository root, start the capture backend with:

```sh
python3 -B -m backend --reset-on-startup --vocab-size YOUR_TOKENIZER_VOCAB_SIZE
```

Replace `YOUR_TOKENIZER_VOCAB_SIZE` with the confirmed integer size. Each successful start resets `prompt_features.current.csv` and `submitted_features.current.csv`. This mode enables submission tracking and keeps previously named captures available. Start the collector with `--track-submissions` so confirmed capture events populate the submissions file.

In another terminal, run Flask from the same directory:

```sh
env TOK_SUBMISSIONS_CSV=submitted_features.current.csv TOK_INTERFACE_HOST=0.0.0.0 python3 -m interface.app
```

Flask starts at port 5000. Its `GET /api/usage` endpoint returns `{"tokens":0,"scale":5000}` at the start of a session and updates as submissions are recorded. Flask can stay running when the capture backend restarts.

On the Pi, set `TOK_API_URL=http://YOUR_MAC_LAN_IP:5000/api/usage` in `hardware/.env` or in its environment before starting the display. Replace `YOUR_MAC_LAN_IP` with your Mac's address on the Pi's network. The display can also use the Mac's `.local` hostname if the Pi can resolve it.

For live draft estimates and the display’s double-tap reset setup, see the [API contract](CONTRACT.md).

### Diagnose a missed submission

Set `TOK_DIAGNOSTICS=1` on the backend, collector, and interface when you restart them with your usual arguments and environment. Each process writes diagnostics to standard error. To save a log, append `2>/tmp/tok-capture.log` to the collector command and use different filenames for the other processes.

Paste the large prompt, wait for Live draft to update, send it with plain Enter, then click **Refresh Usage** in Tok. Compare the logs:

- The collector reports the captured draft size, whether Enter started a send candidate, and why the candidate was confirmed or cancelled. A confirmed candidate has an ID you can match to the backend log.
- The backend reports accepted submissions and rejection reasons, including the request size when it exceeds the 16 MiB limit.
- The interface reports the CSV identity and size, the active reset offset, and how many rows and tokens it counted when the file changes. If the backend accepts a submission and the interface still shows zero, check that `TOK_SUBMISSIONS_CSV` points to the file the backend is writing.

The diagnostic lines contain sizes, counts, and status codes. They omit prompt text.

## Project layout

| Path | Role |
| --- | --- |
| [capture/TokCapture.swift](capture/TokCapture.swift) | macOS composer detection, capture, and send inference |
| [backend/](backend/) | Python CLI, local HTTP API, feature extraction, and CSV export |
| [examples/](examples/) | Synthetic data for testing the model handoff |
| [interface/](interface/) | Flask web interface and token usage API |
| [hardware/](hardware/) | Raspberry Pi display client |
| [CONTRACT.md](CONTRACT.md) | API contract and Mac-to-Pi setup |
| [PLAN.md](PLAN.md) | Capture verification and follow-up work |
