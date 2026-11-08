# Tok capture and CSV handoff

## Backend layout

| File | Responsibility |
|---|---|
| `backend/__main__.py` | CLI arguments and capture file setup |
| `backend/server.py` | Load dashboard assets and start the loopback server |
| `backend/http_api.py` and `backend/payloads.py` | HTTP routes and collector message validation |
| `backend/store.py` | Capture state, session counters, and synchronization |
| `backend/analyzer.py` and `backend/feature_csv.py` | Feature extraction and CSV output |
| `backend/dashboard/` | Dashboard markup, styles, and refresh logic |

Tok detects the frontmost supported app on macOS, reads its focused ChatGPT composer through Accessibility, and sends draft snapshots to a local Python backend. The backend writes numeric features to CSV for the AI engineer to run through JetonCount.

## Capture a session

From the project root, start the backend with Python 3.9 or later:

```sh
python3 -B -m backend
```

Tok creates a timestamped draft CSV and prints its path. You can supply a preferred name with `--csv`. If the file already exists, Tok adds a numbered suffix and keeps the previous capture. If your engineer has confirmed the target tokenizer's vocabulary size, pass it with `--vocab-size N`. Otherwise, the CSV leaves that column blank for the engineer to fill before inference.

In another terminal, compile and start the collector:

```sh
swiftc capture/TokCapture.swift -o /tmp/tok-capture
/tmp/tok-capture
```

Enable Accessibility for the collector or its launcher as identified by macOS in **System Settings → Privacy & Security → Accessibility**, then relaunch it. In Safari or Chrome, open `https://chatgpt.com` and focus the prompt composer. The browser must expose the composer and the web area's URL in its Accessibility tree. In `--probe` mode, look for `composer detected` or a message about what the probe could not verify.

Tok uses foreground app notifications to start and stop watching a supported app. Within that app, it subscribes to Accessibility focus changes and to value changes on the verified composer. It groups bursts of events into one read after about 80 ms. A 400 ms fallback runs if the app or editor rejects a subscription. A slower 1.5-second check covers missed events and refreshes the backend state. Both checks stop when the foreground app is outside Tok's allowlist. [Apple Accessibility notifications](https://developer.apple.com/documentation/applicationservices/axnotificationconstants_h)

For native ChatGPT, run the collector with `TOK_NATIVE_BUNDLE_ID` set to the installed app's verified bundle identifier. Start with `--probe` and focus the composer to see its Accessibility role and identifier. Set `TOK_NATIVE_COMPOSER_ID` to the verified editor identifier and run again without `--probe`. Probe mode reports metadata without reading draft text.

For Codex, the collector recognizes `com.openai.codex` automatically. Run `/tmp/tok-capture --probe`, switch to Codex, and focus its message box. If the probe reports a stable editor or editor container identifier, run capture with `TOK_CODEX_COMPOSER_ID` set to that identifier. Check that the identifier is specific to the composer before enabling capture. Restart an older backend with a fresh CSV to pick up the Codex source.

Use `curl -fsS http://127.0.0.1:8765/reading` to check the current source, capture status, and features. Stop the backend before sharing the session file. Capture is local and the output file contains only numeric features. The collector works without a browser extension.

If Safari exposes an unlabeled text area after typing starts, use `--allow-unidentified-safari-editor` for a controlled test. This mode can read another focused, unlabeled text area on the verified ChatGPT site, so keep focus in the prompt composer during the test. Combine the flag with `--probe` to inspect detection without reading the draft.

## CSV contract

[examples/prompt_features.synthetic.csv](examples/prompt_features.synthetic.csv) is a sample generated from synthetic drafts. Its example vocabulary size, `2560`, is for demonstration. Use the engineer's chosen tokenizer size for actual inference.

The CSV has seven columns in model input order:

```csv
chars,words,avg_chars_per_word,punctuation_ratio,symbol_ratio,longest_word_chars,vocab_size
```

Each row represents one changed, nonempty draft snapshot. One prompt can produce multiple rows while it is edited. Revisions received out of order, unchanged refreshes, and empty or unreadable snapshots produce no rows. Counts use Python Unicode code points and Unicode word matches. Ratios are fractions of all characters, and punctuation and symbol sets overlap. A blank vocabulary size means unknown. The engineer should supply it before running the model and apply the model's preprocessing on their side.

## Verify without UI capture

With the backend running, send a synthetic draft:

```sh
curl -fsS -X PUT http://127.0.0.1:8765/draft \
  -H 'Content-Type: application/json' \
  -d '{"revision":1,"source":"chrome","status":"ready","draft":"Explain this function."}'
```

Use a separate CSV session for synthetic checks. [PLAN.md](PLAN.md) tracks live capture verification and the later pricing and Raspberry Pi work.

## Test submission tracking

Start a new backend session with fresh filenames, and run the collector with submission tracking enabled:

```sh
python3 -B -m backend --track-submissions
```

```sh
/tmp/tok-capture --track-submissions --allow-unidentified-safari-editor
```

If prompted, allow **Input Monitoring** for the collector or its launcher in System Settings and restart the collector. Tok uses a listen-only key event tap. It does not save keystrokes. Tracking requires a nonempty verified composer, plain Enter, and that same composer becoming empty within 1.2 seconds. Shift+Enter, a draft cleared without Enter, and switching apps do not qualify. This is an inference, so an app that replaces the composer or clears it after the timeout may be missed. The row uses the latest snapshot observed before Enter.

The dashboard shows inferred submissions and total submitted characters since backend launch. A display client can read the same totals at `http://127.0.0.1:8765/session`. This endpoint is local to the Mac. The submissions CSV contains one seven-feature row per accepted inference. Token totals require the engineer's model output.



## Estimate tokens from a capture CSV

From the repository root, run:

```sh
python3 -B -m backend --estimate-csv examples/prompt_features.synthetic.csv
```

The command reports the estimate and method for each row, plus their sum. Use a `submitted_features.*.csv` file for a session total because the draft CSV contains intermediate edits. The exporter and estimator use the exact seven-column header above. Every nonempty row supplies all seven raw values to the pinned JetonCount checkpoint. The estimator requires `torch`, `transformers`, and `safetensors`. Pass `--vocab-size` when starting capture to fill that column, or supply it during estimation to fill blank cells. Use the target tokenizer's confirmed vocabulary size. A nonpositive or nonfinite model prediction produces a result labeled `heuristic_fallback`.

The first cell in `JetonCount_Inference.ipynb` runs the same estimator from a notebook. Run that cell from the repository root and set the path to your capture CSV. The existing Databricks examples are separate cells that accept raw text.

To show the submission total on the interface and hardware API, start Flask with the submissions CSV path:

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
