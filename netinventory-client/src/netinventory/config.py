from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path
    db_path: Path
    evidence_dir: Path
    state_dir: Path
    secret_path: Path


@dataclass(frozen=True)
class HubSettings:
    track_base_url: str
    public_path: str
    github_repo: str
    ui_bind: str


def get_app_paths() -> AppPaths:
    env_root = os.environ.get("NETINV_HOME")
    if env_root:
        root = Path(env_root).expanduser()
    else:
        root = Path.home() / ".local" / "share" / "netinventory"

    db_path = root / "netinventory.sqlite3"
    evidence_dir = root / "evidence"
    state_dir = root / "state"
    secret_path = state_dir / "agent.secret"
    return AppPaths(
        root=root,
        db_path=db_path,
        evidence_dir=evidence_dir,
        state_dir=state_dir,
        secret_path=secret_path,
    )


def get_hub_settings() -> HubSettings:
    track_base_url = os.environ.get("TRACK_BASE_URL", "https://track.praktijkpioniers.com").rstrip("/")
    public_path = os.environ.get("NETINV_PUBLIC_PATH", "/netinventory-client/").strip() or "/netinventory-client/"
    if not public_path.startswith("/"):
        public_path = "/" + public_path
    if not public_path.endswith("/"):
        public_path = public_path + "/"
    github_repo = os.environ.get("TRACK_GITHUB_REPO", "https://github.com/praktijkpioniers/track.git").strip()
    ui_bind = os.environ.get("NETINV_UI_BIND", "127.0.0.1:8888").strip() or "127.0.0.1:8888"
    return HubSettings(
        track_base_url=track_base_url,
        public_path=public_path,
        github_repo=github_repo,
        ui_bind=ui_bind,
    )
