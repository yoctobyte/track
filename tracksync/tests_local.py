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

import requests

from app import create_app
from sync_core import ConfigStore, public_environments, resolve_artifact_file, scan_artifact_roots, sign_request, verify_signature


PAIR_SECRET = "pair-secret-for-local-test"


def assert_true(value, message: str) -> None:
    if not value:
        raise AssertionError(message)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_config(
    data_dir: Path,
    host_id: str,
    local_secret: str,
    peers: list[dict],
    artifact_roots: list[dict] | None = None,
    environments: list[dict] | None = None,
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "config.json"
    path.write_text(
        json.dumps(
            {
                "host_id": host_id,
                "secret": local_secret,
                "peers": peers,
                "artifact_roots": artifact_roots or [],
                "environments": environments or [],
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


def signed_headers(host_id: str, secret: str, method: str, path: str, body: bytes = b"") -> dict[str, str]:
    timestamp = str(int(time.time()))
    return {
        "X-Track-Sync-Host": host_id,
        "X-Track-Sync-Timestamp": timestamp,
        "X-Track-Sync-Signature": sign_request(secret, method, path, timestamp, body),
    }


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
    credentialed_peer = store.add_peer(
        "Dev Host",
        "http://127.0.0.1:9998/",
        "dev-secret",
        location_slug="Museum Main",
        username="rene",
        password="local-password",
    )
    assert_true(credentialed_peer["location_slug"] == "museum-main", "peer location should be slugged")
    assert_true(credentialed_peer["username"] == "rene", "peer username should persist locally")
    assert_true(credentialed_peer["password"] == "local-password", "peer password should persist locally")
    store.update_peer_status("stable-server", "ok")
    updated = next(peer for peer in store.load().peers if peer["id"] == "stable-server")
    assert_true(updated["last_status"] == "ok", "peer status should persist")
    assert_true(updated["last_sync_at"], "peer sync timestamp should persist")
    environment = store.add_environment("Museum Main", "Museum Main", "admin", "env-password")
    assert_true(environment["slug"] == "museum-main", "environment slug should be normalized")
    assert_true(environment["password"] == "env-password", "environment password should persist locally")
    public = public_environments(store.load())
    assert_true(public[0]["slug"] == "museum-main", "public environment should include slug")
    assert_true("password" not in public[0], "public environment must not export password")
    assert_true("username" not in public[0], "public environment must not export username")


def test_artifact_manifest(tmpdir: Path) -> None:
    root = tmpdir / "artifacts"
    root.mkdir()
    (root / "small.txt").write_text("small documentation\n", encoding="utf-8")
    (root / "space name.txt").write_text("space path\n", encoding="utf-8")
    (root / "large.bin").write_bytes(b"x" * 1024)
    (root / "secret.key").write_text("do-not-sync\n", encoding="utf-8")
    nested = root / "derived"
    nested.mkdir()
    (nested / "mesh.glb").write_bytes(b"glb")

    data_dir = tmpdir / "artifact-config"
    write_config(
        data_dir,
        "host-a",
        "host-a-local",
        [],
        [
            {
                "id": "docs",
                "path": str(root),
                "tier": "small",
                "record_type": "test.docs",
                "include": ["*.txt", "derived/*.glb", "*.bin"],
                "exclude": ["*.key"],
            }
        ],
    )
    cfg = ConfigStore(data_dir).load()
    files = scan_artifact_roots(cfg)
    rel_paths = {item["relative_path"] for item in files}
    assert_true(rel_paths == {"small.txt", "space name.txt", "large.bin", "derived/mesh.glb"}, str(rel_paths))
    by_path = {item["relative_path"]: item for item in files}
    assert_true(by_path["small.txt"]["tier"] == "small", "tier should propagate")
    assert_true(by_path["small.txt"]["record_type"] == "test.docs", "record_type should propagate")
    assert_true(by_path["small.txt"]["sha256"], "sha256 should be present")
    assert_true(by_path["large.bin"]["size"] == 1024, "size should be present")
    assert_true(by_path["derived/mesh.glb"]["download_path"] == "/api/v1/files/docs/derived/mesh.glb", "download path should be present")
    assert_true(by_path["space name.txt"]["download_path"] == "/api/v1/files/docs/space%20name.txt", "encoded download path should be present")
    assert_true(resolve_artifact_file(cfg, "docs", "small.txt") == root / "small.txt", "configured file should resolve")
    assert_true(resolve_artifact_file(cfg, "docs", "../secret.key") is None, "path traversal should fail")
    assert_true(resolve_artifact_file(cfg, "docs", "secret.key") is None, "excluded file should not resolve")

    old_env = os.environ.copy()
    os.environ["TRACKSYNC_DATA_DIR"] = str(data_dir)
    try:
        app = create_app()
    finally:
        os.environ.clear()
        os.environ.update(old_env)
    client = app.test_client()
    timestamp = str(int(time.time()))
    path = "/api/v1/files/docs/small.txt"
    headers = {
        "X-Track-Sync-Host": "host-a",
        "X-Track-Sync-Timestamp": timestamp,
        "X-Track-Sync-Signature": sign_request("host-a-local", "GET", path, timestamp, b""),
    }
    response = client.get(path, headers=headers)
    assert_true(response.status_code == 200, f"signed artifact download should pass, got {response.status_code}")
    assert_true(response.data == b"small documentation\n", "downloaded artifact content should match")
    assert_true(client.get(path).status_code == 401, "unsigned artifact download should fail")

    encoded_path = "/api/v1/files/docs/space%20name.txt"
    timestamp = str(int(time.time()))
    encoded_headers = {
        "X-Track-Sync-Host": "host-a",
        "X-Track-Sync-Timestamp": timestamp,
        "X-Track-Sync-Signature": sign_request("host-a-local", "GET", encoded_path, timestamp, b""),
    }
    encoded_response = client.get(encoded_path, headers=encoded_headers)
    assert_true(encoded_response.status_code == 200, f"encoded artifact download should pass, got {encoded_response.status_code}")
    assert_true(encoded_response.data == b"space path\n", "encoded downloaded artifact content should match")


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

    environment_store = ConfigStore(data_dir)
    environment_store.add_environment("Museum", "Museum", "admin", "not-exported")
    timestamp = str(int(time.time()))
    manifest_path = "/api/v1/manifest"
    manifest_headers = {
        "X-Track-Sync-Host": "host-a",
        "X-Track-Sync-Timestamp": timestamp,
        "X-Track-Sync-Signature": sign_request("host-a-local", "GET", manifest_path, timestamp, b""),
    }
    manifest = client.get(manifest_path, headers=manifest_headers)
    assert_true(manifest.status_code == 200, f"signed manifest should pass, got {manifest.status_code}")
    exported_env = manifest.json["environments"][0]
    assert_true(exported_env["slug"] == "museum", "manifest should export environment slug")
    assert_true("password" not in exported_env, "manifest must not export environment password")
    assert_true("username" not in exported_env, "manifest must not export environment username")


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
        assert_true(peer_after["last_status"].startswith("ok: host-b / 0 records / 0 files"), peer_after["last_status"])
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


def test_two_process_artifact_sync(tmpdir: Path) -> None:
    port_a = free_port()
    port_b = free_port()
    data_a = tmpdir / "process-host-a"
    data_b = tmpdir / "process-host-b"
    artifact_root = tmpdir / "process-host-b-artifacts"
    artifact_root.mkdir()
    (artifact_root / "gpu mesh.glb").write_bytes(b"mesh-from-gpu")
    (artifact_root / "secret.key").write_text("do-not-sync\n", encoding="utf-8")

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
                "base_url": f"http://127.0.0.1:{port_a}",
                "secret": PAIR_SECRET,
                "enabled": True,
                "created_at": "2026-04-28T00:00:00Z",
                "last_sync_at": "",
                "last_status": "new",
            }
        ],
        [
            {
                "id": "map3d-derived-large",
                "path": str(artifact_root),
                "tier": "derived-large",
                "record_type": "map3d.model_artifact",
                "include": ["*.glb"],
                "exclude": ["*.key"],
                "enabled": True,
            }
        ],
    )

    processes = []
    app_path = Path(__file__).resolve().parent / "app.py"
    try:
        for data_dir, port in ((data_a, port_a), (data_b, port_b)):
            env = os.environ.copy()
            env["TRACKSYNC_DATA_DIR"] = str(data_dir)
            env["TRACKSYNC_ADMIN_PASSWORD"] = "admin-test"
            env["PYTHONPATH"] = str(Path(__file__).resolve().parent)
            processes.append(subprocess.Popen(
                [sys.executable, str(app_path), "--host", "127.0.0.1", "--port", str(port)],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ))

        wait_for_http(f"http://127.0.0.1:{port_a}/login")
        wait_for_http(f"http://127.0.0.1:{port_b}/login")

        manifest_path = "/api/v1/manifest"
        manifest = requests.get(
            f"http://127.0.0.1:{port_b}{manifest_path}",
            headers=signed_headers("host-a", PAIR_SECRET, "GET", manifest_path),
            timeout=5,
        )
        assert_true(manifest.status_code == 200, manifest.text)
        files = manifest.json()["files"]
        assert_true(len(files) == 1, str(files))
        assert_true(files[0]["relative_path"] == "gpu mesh.glb", str(files))
        assert_true(files[0]["tier"] == "derived-large", str(files))
        assert_true(files[0]["download_path"] == "/api/v1/files/map3d-derived-large/gpu%20mesh.glb", str(files))

        download_path = files[0]["download_path"]
        downloaded = requests.get(
            f"http://127.0.0.1:{port_b}{download_path}",
            headers=signed_headers("host-a", PAIR_SECRET, "GET", download_path),
            timeout=5,
        )
        assert_true(downloaded.status_code == 200, downloaded.text)
        assert_true(downloaded.content == b"mesh-from-gpu", "downloaded GPU artifact should match")
        assert_true(requests.get(f"http://127.0.0.1:{port_b}{download_path}", timeout=5).status_code == 401, "unsigned download should fail")

        excluded_path = "/api/v1/files/map3d-derived-large/secret.key"
        excluded = requests.get(
            f"http://127.0.0.1:{port_b}{excluded_path}",
            headers=signed_headers("host-a", PAIR_SECRET, "GET", excluded_path),
            timeout=5,
        )
        assert_true(excluded.status_code == 404, "excluded artifact should not be served")

        admin_session = requests.Session()
        login = admin_session.post(f"http://127.0.0.1:{port_a}/login", data={"password": "admin-test"}, timeout=5)
        assert_true(login.status_code == 200, f"admin login should pass, got {login.status_code}")
        sync_response = admin_session.post(f"http://127.0.0.1:{port_a}/sync/host-b", allow_redirects=False, timeout=10)
        assert_true(sync_response.status_code in {302, 303}, f"sync should redirect, got {sync_response.status_code}")
        config_after = json.loads((data_a / "config.json").read_text(encoding="utf-8"))
        status = config_after["peers"][0]["last_status"]
        assert_true(status.startswith("ok: host-b / 0 records / 1 files"), status)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
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
        test_artifact_manifest(tmpdir)
        test_api_auth(tmpdir)
        test_localhost_peer_handshake(tmpdir)
        test_two_process_artifact_sync(tmpdir)


if __name__ == "__main__":
    main()
