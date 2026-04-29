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
from sync_core import (
    ConfigStore,
    default_pull_policy,
    discover_subprojects,
    peer_allows_subproject,
    peer_artifacts_dir,
    public_environments,
    pull_artifacts,
    resolve_artifact_file,
    scan_artifact_roots,
    sign_request,
    subproject_of,
    verify_signature,
)


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


class FakeResponse:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content


def test_pull_artifacts_policy(tmpdir: Path) -> None:
    assert_true(subproject_of("map3d.model_artifact") == "map3d", "subproject prefix should be parsed")
    assert_true(subproject_of("netinventory.host") == "netinventory", "subproject prefix should be parsed")
    assert_true(subproject_of("") == "", "empty record_type should give empty subproject")

    default_peer = {"id": "peer", "pull_policy": default_pull_policy()}
    assert_true(not peer_allows_subproject(default_peer, "map3d"), "default policy should disable map3d")
    assert_true(peer_allows_subproject(default_peer, "netinventory"), "default policy should enable netinventory")
    assert_true(peer_allows_subproject(default_peer, "quicktrack"), "default policy should enable unknown subprojects")

    no_policy_peer = {"id": "peer"}
    assert_true(not peer_allows_subproject(no_policy_peer, "map3d"), "peers with no pull_policy field should still get the canonical default (map3d off)")
    assert_true(peer_allows_subproject(no_policy_peer, "netinventory"), "peers with no pull_policy field should pull other subprojects")

    # Producer-side artifacts simulated as in-memory bytes; manifest mimics what /api/v1/manifest emits.
    map3d_body = b"large-mesh-bytes"
    netinv_body = b"host-record-json"
    producer_files = {
        "/api/v1/files/map3d-derived/scan.glb": FakeResponse(200, map3d_body),
        "/api/v1/files/netinv-evidence/host.json": FakeResponse(200, netinv_body),
    }
    manifest = {
        "files": [
            {
                "artifact_id": "map3d-derived:abc:scan.glb",
                "root_id": "map3d-derived",
                "record_type": "map3d.model_artifact",
                "tier": "derived-large",
                "relative_path": "scan.glb",
                "size": len(map3d_body),
                "sha256": __import__("hashlib").sha256(map3d_body).hexdigest(),
                "download_path": "/api/v1/files/map3d-derived/scan.glb",
            },
            {
                "artifact_id": "netinv-evidence:def:host.json",
                "root_id": "netinv-evidence",
                "record_type": "netinventory.host",
                "tier": "evidence",
                "relative_path": "host.json",
                "size": len(netinv_body),
                "sha256": __import__("hashlib").sha256(netinv_body).hexdigest(),
                "download_path": "/api/v1/files/netinv-evidence/host.json",
            },
        ]
    }

    data_dir = tmpdir / "pull-policy"
    write_config(data_dir, "host-a", "host-a-local", [])
    cfg = ConfigStore(data_dir).load()
    peer = {"id": "host-b", "pull_policy": default_pull_policy()}

    def getter(path: str) -> FakeResponse:
        if path not in producer_files:
            return FakeResponse(404, b"")
        return producer_files[path]

    counts = pull_artifacts(cfg, peer, manifest, getter)
    assert_true(counts["pulled"] == 1, f"netinv should be pulled, got {counts}")
    assert_true(counts["skipped_policy"] == 1, f"map3d should be skipped by policy, got {counts}")
    assert_true(counts["skipped_exists"] == 0, f"no existing files yet, got {counts}")
    assert_true(counts["failed"] == 0, f"no failures expected, got {counts}")

    landed = peer_artifacts_dir(cfg, "host-b") / "netinv-evidence" / "host.json"
    assert_true(landed.is_file(), f"netinv artifact should land at {landed}")
    assert_true(landed.read_bytes() == netinv_body, "landed bytes should match")
    map3d_landed = peer_artifacts_dir(cfg, "host-b") / "map3d-derived" / "scan.glb"
    assert_true(not map3d_landed.exists(), "map3d artifact must not be pulled under default policy")

    # Re-running should skip the already-present netinv file via sha256 match.
    counts_again = pull_artifacts(cfg, peer, manifest, getter)
    assert_true(counts_again["pulled"] == 0, f"second pass should pull nothing, got {counts_again}")
    assert_true(counts_again["skipped_exists"] == 1, f"netinv should be skip-exists, got {counts_again}")
    assert_true(counts_again["skipped_policy"] == 1, f"map3d still skipped by policy, got {counts_again}")

    # Enabling map3d on this peer should pull it on the next run.
    enabled_peer = {"id": "host-b", "pull_policy": {"default": True, "subprojects": {}}}
    counts_enabled = pull_artifacts(cfg, enabled_peer, manifest, getter)
    assert_true(counts_enabled["pulled"] == 1, f"enabling map3d should pull it, got {counts_enabled}")
    assert_true(counts_enabled["skipped_policy"] == 0, f"no policy skips when map3d enabled, got {counts_enabled}")
    assert_true(counts_enabled["skipped_exists"] == 1, f"netinv still skip-exists, got {counts_enabled}")
    assert_true(map3d_landed.is_file(), "map3d artifact should now land")
    assert_true(map3d_landed.read_bytes() == map3d_body, "map3d landed bytes should match")

    # sha256 mismatch should quarantine the body and not overwrite a verified target.
    poisoned_manifest = {
        "files": [
            {
                "artifact_id": "netinv-evidence:bad:host.json",
                "root_id": "netinv-evidence",
                "record_type": "netinventory.host",
                "tier": "evidence",
                "relative_path": "fresh.json",
                "size": 4,
                "sha256": "0" * 64,
                "download_path": "/api/v1/files/netinv-evidence/fresh.json",
            }
        ]
    }
    poisoned_files = {"/api/v1/files/netinv-evidence/fresh.json": FakeResponse(200, b"junk")}
    counts_poison = pull_artifacts(cfg, peer, poisoned_manifest, lambda path: poisoned_files.get(path, FakeResponse(404, b"")))
    assert_true(counts_poison["failed"] == 1, f"sha256 mismatch should fail, got {counts_poison}")
    assert_true(counts_poison["pulled"] == 0, f"poisoned download should not land, got {counts_poison}")
    fresh_target = peer_artifacts_dir(cfg, "host-b") / "netinv-evidence" / "fresh.json"
    assert_true(not fresh_target.exists(), "poisoned download must not appear at the target path")
    quarantine_dir = peer_artifacts_dir(cfg, "host-b") / "_bad" / "netinv-evidence"
    quarantined = list(quarantine_dir.glob("fresh.json.*")) if quarantine_dir.exists() else []
    assert_true(len(quarantined) == 1, f"quarantine should hold the bad body, found {quarantined}")
    assert_true(quarantined[0].read_bytes() == b"junk", "quarantined bytes should match what was downloaded")


def test_admin_policy_form(tmpdir: Path) -> None:
    data_dir = tmpdir / "policy-form"
    write_config(
        data_dir,
        "host-a",
        "host-a-local",
        [
            {
                "id": "host-b",
                "name": "Host B",
                "base_url": "http://127.0.0.1:9999",
                "secret": PAIR_SECRET,
                "enabled": True,
                "pull_policy": default_pull_policy(),
                "created_at": "2026-04-28T00:00:00Z",
                "last_sync_at": "",
                "last_status": "new",
            }
        ],
        [
            {
                "id": "netinv-evidence",
                "path": str(tmpdir / "policy-form-empty"),
                "tier": "evidence",
                "record_type": "netinventory.host",
                "include": ["**/*"],
                "enabled": True,
            }
        ],
    )

    cfg = ConfigStore(data_dir).load()
    discovered = discover_subprojects(cfg)
    assert_true("map3d" in discovered, f"map3d should always be a known subproject, got {discovered}")
    assert_true("netinventory" in discovered, f"netinventory should be discovered from artifact roots, got {discovered}")

    old_env = os.environ.copy()
    os.environ["TRACKSYNC_DATA_DIR"] = str(data_dir)
    os.environ["TRACKSYNC_ADMIN_PASSWORD"] = "form-admin"
    try:
        app = create_app()
    finally:
        os.environ.clear()
        os.environ.update(old_env)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["tracksync_admin"] = True

    page = client.get("/")
    assert_true(page.status_code == 200, f"index should render for admin, got {page.status_code}")
    body = page.get_data(as_text=True)
    assert_true("Pull Policy" in body, "policy section should render")
    assert_true("name=\"sub_map3d\"" in body, "per-peer form should expose map3d subproject")
    assert_true("name=\"sub_netinventory\"" in body, "per-peer form should expose discovered subprojects")
    assert_true("Save policy" in body, "save button should render")

    # Flip map3d on, leave the default at on, set netinventory to follow-default.
    response = client.post(
        "/peers/host-b/policy",
        data={
            "default": "on",
            "sub_map3d": "on",
            "sub_netinventory": "default",
            "new_subproject": "Quick Track",
            "new_state": "off",
        },
        follow_redirects=False,
    )
    assert_true(response.status_code in {302, 303}, f"policy form should redirect, got {response.status_code}")

    saved = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    saved_policy = saved["peers"][0]["pull_policy"]
    assert_true(saved_policy["default"] is True, f"default should round-trip, got {saved_policy}")
    assert_true(saved_policy["subprojects"].get("map3d") is True, f"map3d should be enabled, got {saved_policy}")
    assert_true("netinventory" not in saved_policy["subprojects"], f"follow-default should remove key, got {saved_policy}")
    assert_true(saved_policy["subprojects"].get("quick-track") is False, f"new subproject should be slugged and saved, got {saved_policy}")

    # Unknown peer ID should 404.
    missing = client.post("/peers/nope/policy", data={"default": "on"}, follow_redirects=False)
    assert_true(missing.status_code == 404, f"unknown peer should 404, got {missing.status_code}")

    # The new policy should now allow pulling map3d via the runtime allow check.
    cfg2 = ConfigStore(data_dir).load()
    refreshed_peer = next(item for item in cfg2.peers if item["id"] == "host-b")
    assert_true(peer_allows_subproject(refreshed_peer, "map3d"), "after policy change, map3d should be pullable")
    assert_true(peer_allows_subproject(refreshed_peer, "netinventory"), "follow-default should still pull netinventory")
    assert_true(not peer_allows_subproject(refreshed_peer, "quick-track"), "new subproject should be skipped")


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
        # Default pull policy disables map3d; the producer's only artifact is map3d.model_artifact,
        # so the integration should report it as policy-skipped, not pulled.
        assert_true(
            status == "ok: host-b / 0 records / 1 files / pulled 0 / skipped 1p 0e / failed 0",
            status,
        )
        landed = data_a / "peers" / "host-b" / "map3d-derived-large" / "gpu mesh.glb"
        assert_true(not landed.exists(), f"map3d artifact must not land under default policy, found {landed}")
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
        test_pull_artifacts_policy(tmpdir)
        test_admin_policy_form(tmpdir)
        test_localhost_peer_handshake(tmpdir)
        test_two_process_artifact_sync(tmpdir)


if __name__ == "__main__":
    main()
