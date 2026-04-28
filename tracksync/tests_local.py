from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from app import create_app
from sync_core import ConfigStore, sign_request, verify_signature


PAIR_SECRET = "pair-secret-for-local-test"


def assert_true(value, message: str) -> None:
    if not value:
        raise AssertionError(message)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_config(data_dir: Path, host_id: str, local_secret: str, peers: list[dict]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "config.json"
    path.write_text(
        json.dumps(
            {
                "host_id": host_id,
                "secret": local_secret,
                "peers": peers,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def wait_for_http(url: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            urlopen(url, timeout=0.5).read()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.1)
    raise AssertionError(f"Server did not become reachable at {url}: {last_error}")


def test_signature_protocol() -> None:
    body = b'{"hello":"world"}'
    timestamp = str(int(time.time()))
    signature = sign_request("secret", "POST", "/api/v1/example", timestamp, body)
    assert_true(
        verify_signature("secret", "POST", "/api/v1/example", timestamp, body, signature),
        "valid signature should verify",
    )
    assert_true(
        not verify_signature("secret", "GET", "/api/v1/example", timestamp, body, signature),
        "method is part of signature",
    )
    assert_true(
        not verify_signature("secret", "POST", "/api/v1/other", timestamp, body, signature),
        "path is part of signature",
    )
    assert_true(
        not verify_signature("wrong", "POST", "/api/v1/example", timestamp, body, signature),
        "wrong secret should fail",
    )
    old_timestamp = str(int(time.time()) - 1000)
    old_signature = sign_request("secret", "POST", "/api/v1/example", old_timestamp, body)
    assert_true(
        not verify_signature("secret", "POST", "/api/v1/example", old_timestamp, body, old_signature),
        "old timestamps should fail replay window",
    )


def test_config_store_permissions(tmpdir: Path) -> None:
    store = ConfigStore(tmpdir / "store")
    cfg = store.load()
    assert_true(cfg.host_id, "host id should be generated")
    assert_true(cfg.secret, "secret should be generated")
    mode = stat.S_IMODE(store.path.stat().st_mode)
    assert_true(mode == 0o600, f"config mode should be 0600, got {oct(mode)}")
    peer = store.add_peer("Stable Server", "http://127.0.0.1:9999/", "peer-secret")
    assert_true(peer["id"] == "stable-server", "peer id should be normalized")
    assert_true(peer["base_url"] == "http://127.0.0.1:9999", "peer URL should be normalized")
    store.update_peer_status("stable-server", "ok")
    updated = store.load().peers[0]
    assert_true(updated["last_status"] == "ok", "peer status should persist")
    assert_true(updated["last_sync_at"], "peer sync timestamp should persist")


def test_api_auth(tmpdir: Path) -> None:
    data_dir = tmpdir / "api"
    write_config(data_dir, "host-a", "host-a-local", [])
    old_env = os.environ.copy()
    os.environ["TRACKSYNC_DATA_DIR"] = str(data_dir)
    try:
        app = create_app()
    finally:
        os.environ.clear()
        os.environ.update(old_env)

    client = app.test_client()
    assert_true(client.get("/api/v1/hello").status_code == 401, "unsigned API should be rejected")

    timestamp = str(int(time.time()))
    headers = {
        "X-Track-Sync-Host": "host-a",
        "X-Track-Sync-Timestamp": timestamp,
        "X-Track-Sync-Signature": sign_request("host-a-local", "GET", "/api/v1/hello", timestamp, b""),
    }
    response = client.get("/api/v1/hello", headers=headers)
    assert_true(response.status_code == 200, f"signed API should pass, got {response.status_code}")
    assert_true(response.json["host_id"] == "host-a", "hello should expose local host id")

    bad_headers = dict(headers)
    bad_headers["X-Track-Sync-Signature"] = sign_request("bad", "GET", "/api/v1/hello", timestamp, b"")
    assert_true(client.get("/api/v1/hello", headers=bad_headers).status_code == 401, "bad signature should fail")


def test_localhost_peer_handshake(tmpdir: Path) -> None:
    port_b = free_port()
    data_a = tmpdir / "host-a"
    data_b = tmpdir / "host-b"
    write_config(
        data_a,
        "host-a",
        "host-a-local",
        [
            {
                "id": "host-b",
                "name": "Host B",
                "base_url": f"http://127.0.0.1:{port_b}",
                "secret": PAIR_SECRET,
                "enabled": True,
                "created_at": "2026-04-28T00:00:00Z",
                "last_sync_at": "",
                "last_status": "new",
            }
        ],
    )
    write_config(
        data_b,
        "host-b",
        "host-b-local",
        [
            {
                "id": "host-a",
                "name": "Host A",
                "base_url": "http://127.0.0.1:0",
                "secret": PAIR_SECRET,
                "enabled": True,
                "created_at": "2026-04-28T00:00:00Z",
                "last_sync_at": "",
                "last_status": "new",
            }
        ],
    )

    env_b = os.environ.copy()
    env_b["TRACKSYNC_DATA_DIR"] = str(data_b)
    env_b["PYTHONPATH"] = str(Path(__file__).resolve().parent)
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve().parent / "app.py"), "--host", "127.0.0.1", "--port", str(port_b)],
        env=env_b,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for_http(f"http://127.0.0.1:{port_b}/login")

        old_env = os.environ.copy()
        os.environ["TRACKSYNC_DATA_DIR"] = str(data_a)
        try:
            app_a = create_app()
        finally:
            os.environ.clear()
            os.environ.update(old_env)

        client = app_a.test_client()
        with client.session_transaction() as sess:
            sess["tracksync_admin"] = True
        response = client.post("/sync/host-b", follow_redirects=False)
        assert_true(response.status_code in {302, 303}, f"sync action should redirect, got {response.status_code}")

        config_after = json.loads((data_a / "config.json").read_text(encoding="utf-8"))
        peer_after = config_after["peers"][0]
        assert_true(peer_after["last_status"].startswith("ok: host-b / 0 records"), peer_after["last_status"])
        assert_true(peer_after["last_sync_at"], "successful sync should write last_sync_at")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.returncode not in {0, -15, -9}:
            stdout, stderr = process.communicate()
            raise AssertionError(f"peer process failed\nstdout:\n{stdout}\nstderr:\n{stderr}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tracksync-local-test-") as tmp:
        tmpdir = Path(tmp)
        test_signature_protocol()
        test_config_store_permissions(tmpdir)
        test_api_auth(tmpdir)
        test_localhost_peer_handshake(tmpdir)


if __name__ == "__main__":
    main()
