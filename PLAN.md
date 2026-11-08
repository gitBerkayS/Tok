# Tok implementation plan

The current deliverable is a local macOS capture pipeline and a numeric CSV for the AI engineer. The engineer runs JetonCount and owns model preprocessing and calibration. Tok will use the results for a live token and cost display in a later phase.

## Current scope

1. **Detect the foreground source.** Use macOS foreground app notifications. In Safari and Chrome, verify the active Accessibility web area is on `https://chatgpt.com`. For native ChatGPT, match the installed app's verified bundle ID.
2. **Read only a verified composer.** Use the focused Accessibility element and bounded ancestor lookup. Require the known composer identifier before reading the value. Check the main and quick native composers independently. On unsupported, unreadable, or unfocused surfaces, report status and skip recording. This workflow uses no extension or continuous screen capture. [Apple Accessibility API](https://developer.apple.com/documentation/applicationservices/axuielement_h)
3. **Keep collection lightweight.** Subscribe to Accessibility focus changes for the active supported app and value changes for its verified composer. Group bursts of events into one read and use bounded polling when notifications are unavailable or missed. Stop observing and polling when an unrelated app takes focus. Send edits and periodic refreshes to a loopback backend. Reject older revisions and avoid writing duplicates from unchanged refreshes. Measure CPU and edit-to-export latency on the target Mac. [Apple Accessibility observer API](https://developer.apple.com/documentation/applicationservices/axuielement_h)
4. **Export data for the engineer.** Write UTF-8 CSV with one row per changed, nonempty draft. Export the seven raw JetonCount inputs in published order. Use a configured target vocabulary size only when known, otherwise leave it blank. The export contains only numeric features. Keep draft text out of logs and files. [JetonCount configuration](https://huggingface.co/fromziro/JetonCount/blob/main/config.json)
5. **Operate locally.** Start a named CSV session explicitly, provide a diagnostic probe and health/current-state endpoints, and mark readings stale after a collector disconnect. Use a fresh file per session to avoid overwriting previous data. Add start-at-login and pause/resume controls after verifying capture behavior.

## Acceptance checks

| Area | Check |
|---|---|
| Safari, Chrome, and native ChatGPT | Type, paste, delete, clear, and switch apps. Verify snapshots come from the focused prompt composer only. Record which app versions and native windows expose readable fields. |
| CSV | Confirm exact column order, correct counts for prose and code, correct Unicode handling, blank or configured vocabulary size, and no prompt text. Verify that refreshes and out-of-order revisions add no rows. |
| Handoff | The engineer can load the file, resolve missing vocabulary sizes, and run their preprocessing and JetonCount independently. |
| Resource use | Measure idle and active CPU, memory, and the delay between a draft edit and the new CSV row on the target Mac. |

Grammarly documents a desktop app with macOS Accessibility permission, menu bar controls, and controls for which apps and sites activate it. Its integration guide says text must be exposed to Accessibility. Tok applies that pattern with an allowlist for ChatGPT composers and uses Apple's public observer API. Grammarly's documentation does not specify its internal observer or fallback implementation. [Grammarly permissions](https://support.grammarly.com/hc/en-us/articles/360059770451-Why-does-Grammarly-need-access-to-accessibility-features) · [Grammarly integration guide](https://support.grammarly.com/hc/en-us/articles/10139846131213-How-do-I-integrate-Grammarly-with-my-website-or-application) · [Grammarly app and site controls](https://support.grammarly.com/hc/en-us/articles/4406998780813-How-to-choose-where-Grammarly-for-Windows-and-Mac-works)

## Later work

- Package the collector as a menu bar app with visible capture status, pause and quit controls, and an optional launch-at-login setting using Service Management. [Apple SMAppService](https://developer.apple.com/documentation/servicemanagement/smappservice)
- Use the engineer's evaluated estimator for the live reading. Keep a matching tokenizer as a potential fallback and label any validated range. Evaluate short prompts, code, and multilingual text separately.
- Calculate USD API-equivalent cost from the chosen model's published input rate. Track the source and date of each rate. An estimate of the current draft excludes hidden context, prior messages, attachments, and output. [API pricing](https://openai.com/api/pricing/) · [ChatGPT and API billing](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform)
- Add an authenticated, read-only connection to the Pi. Send only counts, cost, and freshness status. Use a console receiver before selecting the LED driver, and expire stale readings on disconnect.
