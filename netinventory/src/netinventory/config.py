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
