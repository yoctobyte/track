from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_host_id(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "track-host"


def safe_slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "default"


def default_host_id() -> str:
    configured = os.environ.get("TRACKSYNC_HOST_ID", "").strip()
    if configured:
        return safe_host_id(configured)
    return safe_host_id(os.uname().nodename)


def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_message(method: str, path: str, timestamp: str, body: bytes) -> bytes:
    text = "\n".join([method.upper(), path, timestamp, body_sha256(body)])
    return text.encode("utf-8")


def sign_request(secret: str, method: str, path: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), canonical_message(method, path, timestamp, body), hashlib.sha256).hexdigest()


def verify_signature(secret: str, method: str, path: str, timestamp: str, body: bytes, signature: str, *, max_skew: int = 300) -> bool:
    if not secret or not timestamp or not signature:
        return False
    try:
        request_time = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - request_time) > max_skew:
        return False
    expected = sign_request(secret, method, path, timestamp, body)
    return hmac.compare_digest(expected, signature)


def normalize_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Peer URL must be an absolute http(s) URL")
    return value


def default_pull_policy() -> dict[str, Any]:
    return {"default": True, "subprojects": {"map3d": False}}


def subproject_of(record_type: str) -> str:
    text = str(record_type or "").strip()
    if not text:
        return ""
    return text.split(".", 1)[0]


def peer_allows_subproject(peer: dict[str, Any], subproject: str) -> bool:
    policy = peer.get("pull_policy") or default_pull_policy()
    subprojects = policy.get("subprojects") or {}
    if subproject in subprojects:
        return bool(subprojects[subproject])
    return bool(policy.get("default", True))


@dataclass
class SyncConfig:
    data_dir: Path
    host_id: str
    secret: str
    peers: list[dict[str, Any]]
    environments: list[dict[str, Any]]
    artifact_roots: list[dict[str, Any]]


class ConfigStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.path = data_dir / "config.json"

    def load(self) -> SyncConfig:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            config = {
                "host_id": default_host_id(),
                "secret": os.environ.get("TRACKSYNC_SECRET", "").strip() or secrets.token_urlsafe(32),
                "peers": [],
                "environments": [],
                "artifact_roots": [],
            }
            self.save_dict(config)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        env_secret = os.environ.get("TRACKSYNC_SECRET", "").strip()
        return SyncConfig(
            data_dir=self.data_dir,
            host_id=safe_host_id(str(data.get("host_id") or default_host_id())),
            secret=env_secret or str(data.get("secret", "")),
            peers=list(data.get("peers", [])),
            environments=list(data.get("environments", [])),
            artifact_roots=list(data.get("artifact_roots", [])),
        )

    def save_dict(self, data: dict[str, Any]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.path.chmod(0o600)

    def add_peer(
        self,
        name: str,
        base_url: str,
        secret: str,
        *,
        location_slug: str = "",
        remote_environment_slug: str = "",
        username: str = "",
        password: str = "",
    ) -> dict[str, Any]:
        config = self.load()
        peer_id = safe_host_id(name)
        remote_env = remote_environment_slug.strip() or location_slug.strip()
        peer = {
            "id": peer_id,
            "name": name.strip() or peer_id,
            "base_url": normalize_base_url(base_url),
            "secret": secret.strip(),
            "remote_environment_slug": safe_slug(remote_env) if remote_env else "",
            "location_slug": safe_slug(remote_env) if remote_env else "",
            "username": username.strip(),
            "password": password,
            "enabled": True,
            "pull_policy": default_pull_policy(),
            "created_at": utcnow_iso(),
            "last_sync_at": "",
            "last_status": "new",
        }
        if not peer["secret"]:
            raise ValueError("Peer secret is required")
        peers = [item for item in config.peers if item.get("id") != peer_id]
        peers.append(peer)
        self.save_dict({
            "host_id": config.host_id,
            "secret": config.secret,
            "peers": peers,
            "environments": config.environments,
            "artifact_roots": config.artifact_roots,
        })
        return peer

    def add_environment(self, slug: str, name: str, username: str = "", password: str = "") -> dict[str, Any]:
        config = self.load()
        env_slug = safe_slug(slug)
        now = utcnow_iso()
        existing = next((item for item in config.environments if safe_slug(str(item.get("slug", ""))) == env_slug), None)
        created_at = str(existing.get("created_at")) if existing else now
        environment = {
            "slug": env_slug,
            "name": name.strip() or env_slug,
            "username": username.strip(),
            "password": password,
            "enabled": True,
            "created_at": created_at,
            "updated_at": now,
        }
        environments = [
            item for item in config.environments
            if safe_slug(str(item.get("slug", ""))) != env_slug
        ]
        environments.append(environment)
        self.save_dict({
            "host_id": config.host_id,
            "secret": config.secret,
            "peers": config.peers,
            "environments": environments,
            "artifact_roots": config.artifact_roots,
        })
        return environment

    def update_peer_policy(self, peer_id: str, default_on: bool, subprojects: dict[str, bool]) -> dict[str, Any]:
        config = self.load()
        normalized = {safe_slug(str(name)): bool(value) for name, value in subprojects.items() if str(name).strip()}
        target: dict[str, Any] | None = None
        for peer in config.peers:
            if peer.get("id") == peer_id:
                peer["pull_policy"] = {"default": bool(default_on), "subprojects": normalized}
                target = peer
        if target is None:
            raise KeyError(peer_id)
        self.save_dict({
            "host_id": config.host_id,
            "secret": config.secret,
            "peers": config.peers,
            "environments": config.environments,
            "artifact_roots": config.artifact_roots,
        })
        return target

    def update_peer_status(self, peer_id: str, status: str) -> None:
        config = self.load()
        for peer in config.peers:
            if peer.get("id") == peer_id:
                peer["last_status"] = status
                peer["last_sync_at"] = utcnow_iso()
        self.save_dict({
            "host_id": config.host_id,
            "secret": config.secret,
            "peers": config.peers,
            "environments": config.environments,
            "artifact_roots": config.artifact_roots,
        })


def public_environments(config: SyncConfig) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for environment in config.environments:
        slug = safe_slug(str(environment.get("slug", "")))
        items.append({
            "slug": slug,
            "name": str(environment.get("name") or slug),
            "origin_host_id": config.host_id,
            "enabled": bool(environment.get("enabled", True)),
            "created_at": str(environment.get("created_at") or ""),
            "updated_at": str(environment.get("updated_at") or ""),
        })
    return sorted(items, key=lambda item: item["slug"])


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def matches_any(value: str, patterns: list[str]) -> bool:
    return any(fnmatch(value, pattern) for pattern in patterns)


def scan_artifact_roots(config: SyncConfig) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for root_config in config.artifact_roots:
        if not root_config.get("enabled", True):
            continue
        root_id = safe_host_id(str(root_config.get("id") or root_config.get("name") or "artifact-root"))
        raw_path = str(root_config.get("path") or "").strip()
        if not raw_path:
            continue
        root_path = Path(raw_path).expanduser()
        if not root_path.is_absolute():
            root_path = config.data_dir / root_path
        root_path = root_path.resolve()
        if not root_path.exists() or not root_path.is_dir():
            continue

        include_patterns = [str(item) for item in root_config.get("include", ["*", "**/*"])]
        exclude_patterns = [str(item) for item in root_config.get("exclude", [])]
        tier = str(root_config.get("tier") or "artifact")
        record_type = str(root_config.get("record_type") or f"artifact.{root_id}")

        for path in sorted(root_path.rglob("*")):
            if not path.is_file():
                continue
            rel_path = path.relative_to(root_path).as_posix()
            if not matches_any(rel_path, include_patterns):
                continue
            if matches_any(rel_path, exclude_patterns):
                continue
            stat_result = path.stat()
            sha256 = file_sha256(path)
            files.append({
                "artifact_id": f"{root_id}:{sha256}:{rel_path}",
                "root_id": root_id,
                "record_type": record_type,
                "tier": tier,
                "relative_path": rel_path,
                "size": stat_result.st_size,
                "sha256": sha256,
                "modified_at": datetime.fromtimestamp(stat_result.st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "download_path": f"/api/v1/files/{root_id}/{quote(rel_path)}",
            })
    return files


def peer_artifacts_dir(config: SyncConfig, peer_id: str) -> Path:
    return (config.data_dir / "peers" / safe_host_id(peer_id)).resolve()


def discover_subprojects(config: SyncConfig) -> list[str]:
    seen: set[str] = set()
    for root_config in config.artifact_roots:
        sub = subproject_of(str(root_config.get("record_type") or ""))
        if sub:
            seen.add(sub)
    seen.add("map3d")
    return sorted(seen)


def pull_artifacts(
    config: SyncConfig,
    peer: dict[str, Any],
    manifest: dict[str, Any],
    getter: Callable[[str], Any],
) -> dict[str, Any]:
    peer_id = safe_host_id(str(peer.get("id") or ""))
    root_dir = peer_artifacts_dir(config, peer_id)
    pulled = 0
    skipped_policy = 0
    skipped_exists = 0
    failed = 0
    failures: list[dict[str, Any]] = []

    for entry in manifest.get("files", []) or []:
        record_type = str(entry.get("record_type") or "")
        subproject = subproject_of(record_type)
        if not peer_allows_subproject(peer, subproject):
            skipped_policy += 1
            continue

        root_id = safe_host_id(str(entry.get("root_id") or "artifact-root"))
        rel_path = str(entry.get("relative_path") or "").strip()
        expected_sha = str(entry.get("sha256") or "")
        expected_size = int(entry.get("size") or 0)
        if not rel_path or not expected_sha:
            failed += 1
            failures.append({"reason": "manifest-incomplete", "rel_path": rel_path})
            continue

        target = (root_dir / root_id / rel_path).resolve()
        try:
            target.relative_to(root_dir)
        except ValueError:
            failed += 1
            failures.append({"reason": "unsafe-path", "rel_path": rel_path})
            continue

        if target.is_file() and target.stat().st_size == expected_size and file_sha256(target) == expected_sha:
            skipped_exists += 1
            continue

        download_path = str(entry.get("download_path") or "").strip()
        if not download_path.startswith("/"):
            failed += 1
            failures.append({"reason": "bad-download-path", "rel_path": rel_path})
            continue

        response = getter(download_path)
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code != 200:
            failed += 1
            failures.append({"reason": f"http-{status_code}", "rel_path": rel_path})
            continue

        body = getattr(response, "content", b"") or b""
        if hashlib.sha256(body).hexdigest() != expected_sha:
            quarantine_dir = root_dir / "_bad" / root_id
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            stamp = str(int(time.time()))
            quarantine_path = quarantine_dir / f"{Path(rel_path).name}.{stamp}"
            quarantine_path.write_bytes(body)
            failed += 1
            failures.append({"reason": "sha256-mismatch", "rel_path": rel_path})
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.partial")
        tmp.write_bytes(body)
        tmp.replace(target)
        pulled += 1

    return {
        "pulled": pulled,
        "skipped_policy": skipped_policy,
        "skipped_exists": skipped_exists,
        "failed": failed,
        "failures": failures,
    }


def resolve_artifact_file(config: SyncConfig, root_id: str, relative_path: str) -> Path | None:
    normalized_root_id = safe_host_id(root_id)
    for root_config in config.artifact_roots:
        if not root_config.get("enabled", True):
            continue
        current_root_id = safe_host_id(str(root_config.get("id") or root_config.get("name") or "artifact-root"))
        if current_root_id != normalized_root_id:
            continue
        raw_path = str(root_config.get("path") or "").strip()
        if not raw_path:
            return None
        root_path = Path(raw_path).expanduser()
        if not root_path.is_absolute():
            root_path = config.data_dir / root_path
        root_path = root_path.resolve()
        candidate = (root_path / relative_path).resolve()
        if not candidate.is_file() or root_path not in candidate.parents:
            return None
        rel_path = candidate.relative_to(root_path).as_posix()
        include_patterns = [str(item) for item in root_config.get("include", ["*", "**/*"])]
        exclude_patterns = [str(item) for item in root_config.get("exclude", [])]
        if not matches_any(rel_path, include_patterns) or matches_any(rel_path, exclude_patterns):
            return None
        return candidate
    return None
