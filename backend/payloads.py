"""Validate and unpack messages from the macOS collector."""

SOURCES = ("chrome", "safari", "chatgpt", "codex")


def parse_snapshot(payload):
    revision = payload["revision"]
    source = payload["source"]
    status = payload["status"]
    draft = payload.get("draft")
    if type(revision) is not int or revision < 0:
        raise ValueError("Invalid revision")
    if source is not None and source not in SOURCES:
        raise ValueError("Unknown source")
    if status not in ("ready", "inactive", "unavailable"):
        raise ValueError("Unknown status")
    if status == "ready" and (source is None or not isinstance(draft, str)):
        raise ValueError("Ready snapshots need a source and draft")
    if status != "ready" and draft is not None:
        raise ValueError("Only ready snapshots may carry draft text")
    return revision, source, status, draft


def parse_submission(payload):
    event_id = payload["event_id"]
    draft = payload["draft"]
    if not isinstance(event_id, str) or not 1 <= len(event_id) <= 64:
        raise ValueError("Invalid submission ID")
    if payload["source"] not in SOURCES:
        raise ValueError("Unknown source")
    if not isinstance(draft, str) or not draft.strip():
        raise ValueError("Submissions need a nonempty draft")
    return event_id, draft
