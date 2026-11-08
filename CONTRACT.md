# TOK integration contract

How the three parts connect, so we can build them separately and plug them together.

```
model (teammates)  ->  interface/app.py (Flask)  ->  web page / hardware/simulator.py / Pi LCD+OLED
   get_token_count()      GET /api/usage              all read the same JSON
```

## 1. The one interface everything depends on

`GET /api/usage` returns JSON:

```json
{"tokens": 25316, "scale": 50000}
```

| Field | Type | Rules |
|---|---|---|
| `tokens` | int | `>= 0`. Not a bool, not NaN/inf, not a string. |
| `scale` | int | `> 0`. The token budget the bar and percentages are measured against. |

Status `200` on success. The displays treat anything else (or a timeout) as "Refresh failed".
The hardware also accepts a bare number as the body, but please send the object above.

## 2. What the model side has to do

Replace the body of `get_token_count()` in `interface/app.py` so it **returns an int**.
That is the whole change. The page, the simulator and the Pi need nothing else.

```python
def get_token_count():
    ...  # call the model here
    return 12345  # int, >= 0
```

Run `python interface/test_contract.py` before pushing. It fails if the return value breaks the contract.

## 3. Who owns what

| Part | Owner | Files |
|---|---|---|
| Web page + API | Interface owner | `interface/` |
| Pi LCD/OLED, simulator, Gemini comments | Interface owner | `hardware/` |
| Token model | Model teammates | the body of `get_token_count()` + their own module |

## 4. Where things run

- Flask: `interface/app.py`, port 5000. Currently binds to `127.0.0.1` only, so only the same machine can reach it.
- Pi: `ssh hackcamp@hungergame.local`, project in `~/TOK`, Flask and the button script run there, so the Pi reads `http://127.0.0.1:5000/api/usage`.
- Simulator: `hardware/simulator.py`, port 5001, reads the same API.
- Secrets (Gemini key) live in `hardware/.env`, which is git-ignored. Never commit keys.

## 5. Open questions (fill in together, then delete the question)

- [ ] **Model input.** Does the model take a prompt? If yes: the page needs a text box and the API becomes `POST /api/usage` with `{"prompt": "..."}`, and we must decide whose prompt the hardware shows. If no: keep `GET` as is.
- [ ] **Meaning of `tokens`.** Tokens for the last prompt, a running total for the session, or a prediction made before sending? The "over the limit" comments and the history graph depend on this.
- [ ] **Who owns `scale`.** Hard-coded to `50000` in `interface/app.py` (`REFERENCE_SCALE`). Keep, or should the model/config decide?
- [ ] **Latency.** The Pi gives up after 5 seconds and the Gemini comment after 4. What is the model's worst-case time?
- [ ] **Failure behaviour.** Should `get_token_count()` raise on failure (page shows an error) or return a fallback? Currently an exception gives a 500, which the displays show as "Refresh failed".
- [ ] **Network.** Do the Pi or a phone need to reach Flask on another machine? If yes, use `host="0.0.0.0"` and agree which machine runs it.
- [ ] **Dependencies.** Libraries the model needs (`tiktoken`, Hugging Face, API keys) and who adds them to `interface/requirements.txt`.

## 6. Changing the contract

If the JSON shape changes (new field, POST, different scale), update this file in the same commit,
and tell the interface owner so the page, `hardware/tok_display.py` and the simulator can be updated.
