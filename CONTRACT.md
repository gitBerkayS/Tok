# Tok API contract for Raspberry Pi

The Pi display reads the estimated token total for the current capture session from Flask. The capture backend writes submitted prompt features to a CSV on the Mac. Flask reads that CSV, estimates each submission with JetonCount, and adds the estimates. The Pi needs the API URL and does not need the CSV or model files.

## Usage endpoint

| Item | Contract |
| --- | --- |
| Method and path | `GET /api/usage` |
| Request | No body or query parameters |
| Address | `http://<local-ip>:5000/api/usage` |
| Success | HTTP `200`, `Content-Type: application/json` |
| Timeout | The current Pi client uses a five-second HTTP timeout |
| Side effects | Reading the endpoint does not record a submission or reset the session |

Example success response:

```json
{"tokens":147,"scale":5000}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `tokens` | Nonnegative integer | Sum of the estimates for inferred submissions recorded since the capture backend started in reset mode or the latest successful double-tap reset. Unsent drafts and edits do not contribute. |
| `scale` | Positive integer | Display reference budget, currently `5000`. The Pi calculates the percentage as `tokens / scale × 100`. Usage may exceed the scale. |

An empty session returns `{"tokens":0,"scale":5000}`. A capture restart resets the total. The Pi should display the new value on its next refresh, even when it is lower than the previous value. Each response is a complete total. The Pi should replace its displayed value with that total.

If Flask cannot read the configured CSV or cannot produce an estimate, it returns HTTP `503` with an `error` string, such as `{"error":"Expected this CSV header: ..."}`. Treat a non-200 response, connection failure, timeout, or invalid JSON as a refresh failure. Do not use zero as a substitute for a failed refresh. A valid zero comes from a successful response.

## Reset endpoint

`POST /api/usage/reset` requires `Authorization: Bearer <TOK_RESET_KEY>` and a configured `TOK_SUBMISSIONS_CSV`. It returns the same JSON shape as the usage endpoint, with zero tokens. The interface saves a cutoff alongside the submissions CSV and counts only rows appended after that point. The cutoff survives interface restarts and applies only to that CSV. Capture continues appending, and both CSVs remain available for export. The live draft endpoint is independent of this cutoff.

## Live draft endpoint

`GET /api/draft` returns the same capture snapshot used by the Capture Monitor, with an estimated token count. Each snapshot includes `tokens`, `scale`, `status`, `source`, `revision`, and `updated_at`. A ready snapshot also includes the seven numeric `features` and the estimation `method`. An inactive, unavailable, or stale composer returns zero with its corresponding status. If Flask cannot reach the capture backend or cannot estimate the draft, it returns HTTP `503`. Live reads do not change the session total at `/api/usage`.

`GET /api/draft/stream` opens a server-sent event connection. It sends the initial snapshot and checks for updates every half second. Each `draft` event carries the same JSON as `GET /api/draft`. A `capture-error` event carries an `error` string while capture or estimation is unavailable, and the stream resumes sending `draft` events after recovery.

```sh
curl -N http://YOUR_MAC_LAN_IP:5000/api/draft/stream
```

Run `env TOK_API_URL=http://YOUR_MAC_LAN_IP:5000/api/usage ./hardware/start.sh --live` from the Pi's checkout to start in live draft mode. While the display is on, tap twice in quick succession to reset the session total and display zero. If started with `--live`, a successful reset switches the display to the session total. Use the touch sensor to switch between the session total and live draft. A single tap refreshes the current mode, and a two-second hold turns the display off. The LCD and attached OLED share the same reading. Live draft mode refreshes about twice per second. Session total mode refreshes about every two seconds, so new submissions show up automatically after a reset.

## Mac setup

Run the capture backend and Flask from the repository root. Replace `YOUR_TOKENIZER_VOCAB_SIZE` with the confirmed integer size.

```sh
python3 -B -m backend --reset-on-startup --vocab-size YOUR_TOKENIZER_VOCAB_SIZE
```

Start the macOS collector with `--track-submissions`. In a separate terminal, start Flask with the fixed submissions CSV path:

```sh
env TOK_SUBMISSIONS_CSV=submitted_features.current.csv TOK_INTERFACE_HOST=0.0.0.0 python3 -m interface.app
```

Reset mode initializes `submitted_features.current.csv` with the seven-column header. Flask can stay running when capture restarts because the file path stays the same. Set `TOK_SUBMISSIONS_CSV` for hardware use. To enable double-tap reset, export `TOK_RESET_KEY` in the Flask environment and set the same private value on the Pi in `hardware/.env`. The interface uses demo values when `TOK_SUBMISSIONS_CSV` is unset. The first model prediction may take longer if the checkpoint has not been loaded.

## Pi setup and verification

1. Put the Mac and Pi on the same reachable network.
2. Set the display endpoint in `hardware/.env` on the Pi or export it before starting the display. Use the Mac's LAN address. A Mac `.local` hostname also works when the Pi can resolve it.
3. From the Pi, check the endpoint before starting the display.

```sh
# hardware/.env
TOK_API_URL=http://YOUR_MAC_LAN_IP:5000/api/usage
```

```sh
curl --fail --max-time 5 http://YOUR_MAC_LAN_IP:5000/api/usage
```

Verify that a new session returns zero, an inferred submission raises the total, and double-tapping returns the total to zero. Submit another prompt and verify that only its estimate contributes to the new total. The existing Pi LCD client and simulator read this endpoint through `hardware/tok_display.py`. The separate `hardware/display.py` client accepts the same URL with `--url`.
