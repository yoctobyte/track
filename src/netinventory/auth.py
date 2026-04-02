from __future__ import annotations

import secrets
from pathlib import Path

from netinventory.config import AppPaths


def load_or_create_shared_secret(paths: AppPaths) -> str:
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    secret_path = paths.secret_path

    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()

    token = secrets.token_urlsafe(24)
    secret_path.write_text(token + "\n", encoding="utf-8")
    try:
        secret_path.chmod(0o600)
    except OSError:
        pass
    return token


def extract_presented_token(headers) -> str | None:
    explicit = headers.get("X-NetInv-Token")
    if explicit:
        return explicit.strip()

    authorization = headers.get("Authorization")
    if not authorization:
        return None

    parts = authorization.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip()
