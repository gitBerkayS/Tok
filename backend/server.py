"""Load dashboard assets and run the backend on the loopback interface."""

from http.server import ThreadingHTTPServer
from pathlib import Path

from .http_api import make_handler


DASHBOARD_DIR = Path(__file__).with_name("dashboard")


def serve(port, store):
    assets = {
        "/": ("text/html; charset=utf-8", (DASHBOARD_DIR / "index.html").read_bytes()),
        "/dashboard.css": ("text/css; charset=utf-8", (DASHBOARD_DIR / "dashboard.css").read_bytes()),
        "/dashboard.js": ("text/javascript; charset=utf-8", (DASHBOARD_DIR / "dashboard.js").read_bytes()),
    }
    with ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, assets)) as server:
        print(f"Tok analyzer on http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
