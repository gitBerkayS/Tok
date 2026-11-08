"""Run the loopback backend with an optional local preview."""

from http.server import ThreadingHTTPServer
from pathlib import Path

from .http_api import make_handler


LOCAL_PREVIEW = Path(__file__).with_name("dashboard.html")


def serve(port, store):
    assets = {}
    if LOCAL_PREVIEW.is_file():
        assets["/"] = ("text/html; charset=utf-8", LOCAL_PREVIEW.read_bytes())
    with ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, assets)) as server:
        print(f"Tok analyzer on http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
