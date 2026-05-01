from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app, load_or_create_simple_upload_token  # noqa: E402
from app.topology import build_topology  # noqa: E402


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def sample_registration() -> dict[str, object]:
    return {
        "kind": "script-shell-admin",
        "timestamp": "2026-04-29T10:00:00+00:00",
        "instance": "testing",
        "description": "field laptop",
        "client_id": "laptop-alpha",
        "payload": {
            "kind": "script-shell-admin",
            "host": {
                "hostname": "field-laptop",
                "fqdn": "field-laptop.local",
                "machine_id": "machine-alpha",
            },
            "network": {
                "interface_addresses": [
                    "lo UNKNOWN 127.0.0.1/8",
                    "wlan0 UP 192.168.44.23/24 fe80::1234/64",
                ],
                "routes": [
                    "default via 192.168.44.1 dev wlan0 proto dhcp metric 600",
                    "192.168.44.0/24 dev wlan0 proto kernel scope link src 192.168.44.23",
                ],
                "default_route": "default via 192.168.44.1 dev wlan0",
                "nameservers": ["192.168.44.1", "1.1.1.1"],
                "external_ip": "203.0.113.10",
            },
        },
        "client": {"remote_addr": "10.0.0.8", "user_agent": "test"},
    }


def test_build_topology_from_registration() -> None:
    topology = build_topology([sample_registration()])
    node_ids = {node["id"] for node in topology["nodes"]}
    relations = {edge["relation"] for edge in topology["edges"]}

    assert_true(topology["summary"]["hosts"] == 1, "expected one host")
    assert_true("host:laptop-alpha" in node_ids, "expected host node")
    assert_true("subnet:192.168.44.0/24" in node_ids, "expected subnet node")
    assert_true("gateway:192.168.44.1" in node_ids, "expected gateway node")
    assert_true("dns:1.1.1.1" in node_ids, "expected dns node")
    assert_true("attached_to_subnet" in relations, "expected subnet edge")
    assert_true("uses_gateway" in relations, "expected gateway edge")
    assert_true("uses_dns" in relations, "expected dns edge")


def test_flask_ingest_rebuilds_topology() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        old_env = {
            "NETINVENTORY_HOST_DATA_DIR": os.environ.get("NETINVENTORY_HOST_DATA_DIR"),
            "NETINVENTORY_HOST_INSTANCE": os.environ.get("NETINVENTORY_HOST_INSTANCE"),
            "NETINVENTORY_HOST_SECRET_KEY": os.environ.get("NETINVENTORY_HOST_SECRET_KEY"),
            "NETINVENTORY_PRIVILEGED_PASSWORD": os.environ.get("NETINVENTORY_PRIVILEGED_PASSWORD"),
        }
        os.environ["NETINVENTORY_HOST_DATA_DIR"] = tmp
        os.environ["NETINVENTORY_HOST_INSTANCE"] = "testing"
        os.environ["NETINVENTORY_HOST_SECRET_KEY"] = "test-secret"
        os.environ["NETINVENTORY_PRIVILEGED_PASSWORD"] = "priv-test"
        try:
            app = create_app()
            client = app.test_client()
            blocked = client.post(
                "/api/simple-ingest",
                data=json.dumps(sample_registration()["payload"]),
                content_type="application/json",
                headers={"X-Track-Client-Id": "laptop-alpha"},
            )
            assert_true(blocked.status_code == 403, "ingest without upload token should fail")
            token = load_or_create_simple_upload_token()
            response = client.post(
                "/api/simple-ingest",
                data=json.dumps(sample_registration()["payload"]),
                content_type="application/json",
                headers={
                    "X-Track-Client-Id": "laptop-alpha",
                    "X-NetInv-Token": token,
                    "X-Forwarded-For": "10.0.0.8",
                },
            )
            assert_true(response.status_code == 200, f"ingest failed: {response.status_code}")

            topology_path = Path(tmp) / "topology" / "summary.json"
            assert_true(topology_path.exists(), "expected topology summary file")
            topology = json.loads(topology_path.read_text(encoding="utf-8"))
            assert_true(topology["summary"]["hosts"] == 1, "expected one persisted host")

            api_response = client.get("/api/topology")
            assert_true(api_response.status_code == 200, f"api failed: {api_response.status_code}")
            api_payload = api_response.get_json()
            assert_true(api_payload["summary"]["nodes"] >= 4, "expected api topology nodes")

            page_response = client.get("/topology")
            assert_true(page_response.status_code == 200, f"page failed: {page_response.status_code}")
            assert_true(b"Guessed Network Graph" in page_response.data, "expected topology page content")

            index_public = client.get("/")
            assert_true(index_public.status_code == 200, "index should render")
            public_body = index_public.get_data(as_text=True)
            assert_true(token not in public_body, "public index must not expose upload token")
            assert_true("NetInventory Client Setup" not in public_body, "public index must not expose pairing block")

            login = client.post("/login", data={"password": "priv-test"}, follow_redirects=True)
            assert_true(login.status_code == 200, "privileged login should work")
            private_body = login.get_data(as_text=True)
            assert_true(token in private_body, "privileged index should expose upload token")
            assert_true("track-netinventory-sync-target-v1" in private_body, "privileged index should expose setup block")
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def main() -> int:
    test_build_topology_from_registration()
    test_flask_ingest_rebuilds_topology()
    print("netinventory-host local tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
