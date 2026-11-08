"""Handle local HTTP routes, request validation, and response formatting."""

import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler

from .payloads import parse_snapshot, parse_submission


MAX_BODY_BYTES = 16 * 1_048_576  # a very long prompt must not be rejected and counted as 0


def make_handler(store, assets):
    """Bind the capture store and dashboard assets to the HTTP handler."""
    diagnostics = os.environ.get("TOK_DIAGNOSTICS") == "1"

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            # Never log request paths or bodies from the capture adapter.
            pass

        def reply(self, code, data):
            self.send_body(code, json.dumps(data).encode(), "application/json")

        def send_body(self, code, body, content_type):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in assets:
                content_type, body = assets[self.path]
                self.send_body(200, body, content_type)
            elif self.path == "/dashboard-data":
                self.reply(200, store.dashboard())
            elif self.path == "/health":
                self.reply(200, {"status": "ok", "mode": "feature_export"})
            elif self.path == "/reading":
                self.reply(200, store.current())
            elif self.path == "/session":
                self.reply(200, store.session())
            else:
                self.reply(404, {"error": "not_found"})

        def do_PUT(self):
            if self.path not in ("/draft", "/submission"):
                self.reply(404, {"error": "not_found"})
                return
            if self.headers.get_content_type() != "application/json":
                self.capture_error(415, "expected_json")
                return
            is_submission = self.path == "/submission"
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > MAX_BODY_BYTES:
                    self.capture_error(413, "draft_too_large", length)
                    return
                if length <= 0:
                    raise ValueError
                payload = json.loads(self.rfile.read(length))
                parse = parse_submission if is_submission else parse_snapshot
                arguments = parse(payload)
            except (KeyError, ValueError, TypeError):
                self.capture_error(400, "invalid_snapshot")
                return
            if is_submission and not store.submission_tracking_enabled:
                self.capture_error(409, "submission_tracking_disabled", length)
                return
            apply = store.submit if is_submission else store.update
            try:
                accepted = apply(*arguments)
            except OSError as error:
                self.capture_error(503, "csv_write_failed", length, errno=error.errno)
                return
            if diagnostics and is_submission:
                event_id, draft = arguments
                # Only echo IDs in the collector's UUID format, never arbitrary request values.
                safe_id = event_id if re.fullmatch(
                    r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", event_id
                ) else "-"
                self.capture_log(
                    f"id={safe_id} accepted={accepted} chars={len(draft)} body_bytes={length}"
                )
            self.reply(200, {"accepted": accepted})

        def capture_error(self, code, reason, length=None, errno=None):
            if diagnostics:
                self.capture_log(f"http={code} reason={reason} body_bytes={length} errno={errno}")
            self.reply(code, {"error": reason})

        def capture_log(self, message):
            print(f"[tok backend] {time.time():.3f} {self.path} {message}", file=sys.stderr, flush=True)

    return Handler
