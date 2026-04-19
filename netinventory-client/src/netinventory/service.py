from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from netinventory.auth import extract_presented_token, load_or_create_shared_secret
from netinventory.config import get_app_paths
from netinventory.export import build_export_bundle_bytes
from netinventory.storage.db import Database
from netinventory.tasks import list_task_definitions


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

        def _add_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-NetInv-Token")

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._add_cors_headers()
            self.end_headers()

        def do_POST(self) -> None:
            paths = get_app_paths()
            db = Database(paths)
            shared_secret = load_or_create_shared_secret(paths)

            if not self._is_authorized(shared_secret):
                self._send_json(
                    HTTPStatus.UNAUTHORIZED,
                    {"error": "unauthorized", "detail": "missing or invalid shared secret"},
                )
                return

            if self.path == "/api/v1/trigger-scan":
                content_length = int(self.headers.get("Content-Length", 0))
                payload_data = {}
                if content_length > 0:
                    try:
                        body = self.rfile.read(content_length).decode("utf-8")
                        payload_data = json.loads(body)
                    except Exception:
                        pass
                
                context_str = payload_data.get("context", "").strip()
                if context_str:
                    from netinventory.context import add_user_context
                    add_user_context(db, entity_kind="network_scan", entity_id="manual", field="rack_location", value=context_str)

                from netinventory.tasks import run_task_once
                from netinventory.core.tasks import TaskTrigger
                run_task_once(db, "current_network_probe", TaskTrigger.MANUAL)

                current = db.get_current_network()
                observation = None if current is None else db.get_latest_observation(current.network_id)
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "current_network": None if current is None else current.to_dict(),
                        "latest_observation": observation,
                    },
                )
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_GET(self) -> None:
            paths = get_app_paths()
            db = Database(paths)
            db.upsert_task_definitions(list_task_definitions())
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
                observation = None if current is None else db.get_latest_observation(current.network_id)
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "current_network": None if current is None else current.to_dict(),
                        "latest_observation": observation,
                    },
                )
                return

            if self.path == "/api/v1/networks":
                self._send_json(HTTPStatus.OK, {"networks": [network.to_dict() for network in db.list_networks()]})
                return

            if self.path == "/api/v1/tasks":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "definitions": db.list_task_definitions(),
                        "recent_runs": db.list_recent_task_runs(),
                    },
                )
                return

            if self.path == "/api/v1/context":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "context": db.list_user_context(),
                    },
                )
                return

            if self.path == "/api/v1/export":
                payload = build_export_bundle_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Content-Disposition", 'attachment; filename="netinventory-export.tar.gz"')
                self.send_header("Content-Length", str(len(payload)))
                self._add_cors_headers()
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
            self._add_cors_headers()
            self.end_headers()
            self.wfile.write(body)

    return RequestHandler


def _parse_bind(bind: str) -> tuple[str, int]:
    if ":" not in bind:
        raise ValueError(f"invalid bind address: {bind!r}")
    host, port_text = bind.rsplit(":", 1)
    return host, int(port_text)
