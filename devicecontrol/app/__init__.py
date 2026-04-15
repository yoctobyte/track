from __future__ import annotations

import os
import re
import secrets
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"
PLAYBOOK_DIR = BASE_DIR / "ansible" / "playbooks"
TRUSTED_PROXY_ADDRS = {"127.0.0.1", "::1"}
SENSITIVE_VAR_RE = re.compile(r"(pass|password|secret|token|key|credential|vault)", re.IGNORECASE)


@dataclass(frozen=True)
class Action:
    id: str
    name: str
    playbook: str
    summary: str
    danger: str = "normal"


ACTIONS: dict[str, Action] = {
    "ping": Action("ping", "Ping", "ping.yml", "Verify Ansible connectivity."),
    "apt-update": Action("apt-update", "Apt Update", "apt-update.yml", "Refresh apt package metadata."),
    "apt-upgrade": Action("apt-upgrade", "Apt Upgrade", "apt-upgrade.yml", "Install safe apt upgrades.", "careful"),
    "reboot": Action("reboot", "Reboot", "reboot.yml", "Reboot selected hosts.", "danger"),
    "update-and-reboot": Action(
        "update-and-reboot",
        "Update + Reboot",
        "update-and-reboot.yml",
        "Upgrade packages and reboot selected hosts.",
        "danger",
    ),
    "screenshot": Action(
        "screenshot",
        "Screenshot",
        "screenshot.yml",
        "Attempt to capture desktop screenshots and fetch them into this environment.",
        "careful",
    ),
}


def sanitize_environment(raw: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", raw.strip().lower()).strip("-")
    return cleaned or "testing"


def load_secret_key(data_dir: Path) -> str:
    configured = os.environ.get("DEVICECONTROL_SECRET_KEY", "").strip()
    if configured:
        return configured
    secret_path = data_dir / ".devicecontrol-secret-key"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    secret_path.write_text(secret + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    return secret


def create_app() -> Flask:
    app = Flask(__name__)
    data_dir = Path(os.environ.get("DEVICECONTROL_DATA_DIR", DEFAULT_DATA_DIR)).expanduser().resolve()
    app.config["SECRET_KEY"] = load_secret_key(data_dir)
    app.config["SESSION_COOKIE_NAME"] = "devicecontrol_session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=1, x_prefix=1)

    default_environment = sanitize_environment(os.environ.get("DEVICECONTROL_ENVIRONMENT", "testing"))
    allow_standalone = os.environ.get("DEVICECONTROL_ALLOW_STANDALONE", "").lower() in {"1", "true", "yes"}
    timeout = int(os.environ.get("DEVICECONTROL_ACTION_TIMEOUT", "1800"))

    def proxy_environment() -> str | None:
        if request.remote_addr not in TRUSTED_PROXY_ADDRS:
            return None
        if request.headers.get("X-Trackhub-Authenticated", "").lower() != "true":
            return None
        env = request.headers.get("X-Trackhub-Environment", "").strip()
        return sanitize_environment(env) if env else None

    def current_environment() -> str:
        env = proxy_environment()
        if env:
            return env
        if allow_standalone:
            return default_environment
        abort(403)

    @app.before_request
    def require_trackhub_access():
        if allow_standalone:
            return None
        if proxy_environment():
            return None
        abort(403)

    def csrf_token() -> str:
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return str(token)

    def require_csrf() -> None:
        submitted = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not submitted or not expected or not secrets.compare_digest(submitted, str(expected)):
            abort(403)

    def env_dir(env: str) -> Path:
        root = data_dir / "environments" / sanitize_environment(env)
        (root / "run_logs").mkdir(parents=True, exist_ok=True)
        (root / "screenshots").mkdir(parents=True, exist_ok=True)
        inventory = root / "inventory.ini"
        if not inventory.exists():
            inventory.write_text("[ungrouped]\n", encoding="utf-8")
        return root

    def inventory_path(env: str) -> Path:
        return env_dir(env) / "inventory.ini"

    def parse_inventory(path: Path) -> tuple[list[str], list[dict[str, object]]]:
        groups: list[str] = []
        hosts: dict[str, dict[str, object]] = {}
        current_group = "ungrouped"

        if not path.exists():
            return groups, []

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                group = line[1:-1].strip()
                if group and ":" not in group:
                    current_group = group
                    if group not in groups:
                        groups.append(group)
                continue
            if line.startswith("["):
                continue

            parts = shlex.split(line, comments=True)
            if not parts:
                continue
            name = parts[0]
            entry = hosts.setdefault(name, {"name": name, "groups": set(), "vars": {}})
            entry["groups"].add(current_group)
            for part in parts[1:]:
                if "=" in part:
                    key, value = part.split("=", 1)
                    entry["vars"][key] = "REDACTED" if SENSITIVE_VAR_RE.search(key) else value

        parsed_hosts = []
        for entry in hosts.values():
            parsed_hosts.append(
                {
                    "name": entry["name"],
                    "groups": sorted(entry["groups"]),
                    "vars": dict(entry["vars"]),
                }
            )
        return groups, sorted(parsed_hosts, key=lambda item: str(item["name"]))

    def safe_target(raw: str) -> str:
        target = raw.strip()
        if not target:
            return ""
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", target):
            abort(400, "Invalid target selector.")
        return target

    def run_log_path(env: str, action_id: str, target: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target_part = re.sub(r"[^A-Za-z0-9_.-]+", "-", target or "all").strip("-")
        return env_dir(env) / "run_logs" / f"{stamp}-{action_id}-{target_part}.log"

    def list_logs(env: str) -> list[dict[str, object]]:
        log_dir = env_dir(env) / "run_logs"
        logs = []
        for path in sorted(log_dir.glob("*.log"), reverse=True)[:50]:
            logs.append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        return logs

    def list_screenshots(env: str) -> list[dict[str, object]]:
        root = env_dir(env) / "screenshots"
        items = []
        for path in sorted(root.rglob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
            items.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "name": path.name,
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        return items

    def ansible_available() -> bool:
        return shutil.which("ansible-playbook") is not None

    @app.context_processor
    def inject_state():
        return {
            "current_environment": current_environment(),
            "actions": ACTIONS,
            "ansible_available": ansible_available(),
            "csrf_token": csrf_token,
        }

    @app.get("/")
    def index():
        env = current_environment()
        groups, hosts = parse_inventory(inventory_path(env))
        return render_template(
            "index.html",
            environment=env,
            inventory_path=inventory_path(env),
            groups=groups,
            hosts=hosts,
            logs=list_logs(env),
            screenshots=list_screenshots(env),
            data_dir=data_dir,
        )

    @app.post("/run/<action_id>")
    def run_action(action_id: str):
        require_csrf()
        action = ACTIONS.get(action_id)
        if action is None:
            abort(404)
        env = current_environment()
        playbook = PLAYBOOK_DIR / action.playbook
        if not playbook.exists():
            abort(500, f"Missing playbook: {action.playbook}")
        target = safe_target(request.form.get("target", ""))
        log_path = run_log_path(env, action_id, target)
        screenshot_dir = env_dir(env) / "screenshots"
        command = [
            "ansible-playbook",
            "-i",
            str(inventory_path(env)),
            "--ssh-common-args",
            "-o BatchMode=yes -o StrictHostKeyChecking=yes -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no",
            str(playbook),
        ]
        if target:
            command.extend(["--limit", target])
        if action_id == "screenshot":
            command.extend(["--extra-vars", f"screenshot_output_dir={screenshot_dir}"])

        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("w", encoding="utf-8") as handle:
            handle.write(f"Started: {started}\n")
            handle.write(f"Environment: {env}\n")
            handle.write(f"Action: {action_id}\n")
            handle.write(f"Target: {target or 'all'}\n")
            handle.write(f"Command: {' '.join(shlex.quote(part) for part in command)}\n\n")
            if not ansible_available():
                handle.write("ERROR: ansible-playbook was not found in PATH.\n")
                return redirect(url_for("view_log", name=log_path.name))
            try:
                run_env = os.environ.copy()
                run_env["ANSIBLE_HOST_KEY_CHECKING"] = "True"
                run_env["ANSIBLE_NOCOLOR"] = "1"
                result = subprocess.run(
                    command,
                    cwd=BASE_DIR,
                    env=run_env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
                handle.write(result.stdout)
                handle.write(f"\nExit code: {result.returncode}\n")
            except subprocess.TimeoutExpired as exc:
                handle.write(exc.stdout or "")
                handle.write(f"\nERROR: action timed out after {timeout} seconds.\n")
        return redirect(url_for("view_log", name=log_path.name))

    @app.get("/logs/<name>")
    def view_log(name: str):
        if "/" in name or name.startswith("."):
            abort(404)
        env = current_environment()
        path = env_dir(env) / "run_logs" / name
        if not path.exists():
            abort(404)
        return render_template(
            "log.html",
            environment=env,
            name=name,
            content=path.read_text(encoding="utf-8", errors="replace"),
        )

    @app.get("/screenshots/<path:name>")
    def screenshot_file(name: str):
        env = current_environment()
        root = env_dir(env) / "screenshots"
        return send_from_directory(root, name)

    return app
