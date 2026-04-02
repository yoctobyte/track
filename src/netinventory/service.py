from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from netinventory.auth import extract_presented_token, load_or_create_shared_secret
from netinventory.config import get_app_paths
from netinventory.export import build_export_bundle_bytes
from netinventory.storage.db import Database


def run_service(bind: str) -> int:
    host, port = _parse_bind(bind)
    server = ThreadingHTTPServer((host, port), _build_handler())
    print(f"service listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _build_handler():
    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "NetInventoryAgent/0.1"

        def do_GET(self) -> None:
            paths = get_app_paths()
            db = Database(paths)
            shared_secret = load_or_create_shared_secret(paths)

            if not self._is_authorized(shared_secret):
                self._send_json(
                    HTTPStatus.UNAUTHORIZED,
                    {"error": "unauthorized", "detail": "missing or invalid shared secret"},
                )
                return

            if self.path == "/api/v1/status":
                self._send_json(HTTPStatus.OK, db.get_status().to_dict())
                return

            if self.path == "/api/v1/current":
                current = db.get_current_network()
                self._send_json(HTTPStatus.OK, {"current_network": None if current is None else current.to_dict()})
                return

            if self.path == "/api/v1/networks":
                self._send_json(HTTPStatus.OK, {"networks": [network.to_dict() for network in db.list_networks()]})
                return

            if self.path == "/api/v1/export":
                payload = build_export_bundle_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Content-Disposition", 'attachment; filename="netinventory-export.tar.gz"')
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def log_message(self, fmt: str, *args) -> None:
            return

        def _is_authorized(self, shared_secret: str) -> bool:
            token = extract_presented_token(self.headers)
            return token == shared_secret

        def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return RequestHandler


def _parse_bind(bind: str) -> tuple[str, int]:
    if ":" not in bind:
        raise ValueError(f"invalid bind address: {bind!r}")
    host, port_text = bind.rsplit(":", 1)
    return host, int(port_text)
