from __future__ import annotations

import os
import json
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
import threading
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlunsplit

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
        "screenshot-fast.yml",
        "Capture desktop screenshots using already-installed tools.",
    ),
    "screenshot-setup": Action(
        "screenshot-setup",
        "Screenshot Setup",
        "screenshot.yml",
        "Install screenshot tools if missing, then capture desktop screenshots.",
        "careful",
    ),
    "collect-stats": Action(
        "collect-stats",
        "Collect Stats",
        "collect-stats.yml",
        "Collect host IPs, load, memory, desktop hints, and runtime-user processes.",
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
    app.config["TRACK_BASE_URL"] = os.environ.get("TRACK_BASE_URL", "/").rstrip("/") or "/"
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
        (root / "stats").mkdir(parents=True, exist_ok=True)
        (root / "display_events").mkdir(parents=True, exist_ok=True)
        (root / "device_events").mkdir(parents=True, exist_ok=True)
        (root / "capture_profiles").mkdir(parents=True, exist_ok=True)
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

    def status_path(log_path: Path) -> Path:
        return log_path.with_suffix(".status")

    def write_status(log_path: Path, status: str, detail: str = "") -> None:
        text = status
        if detail:
            text = f"{text}\n{detail}"
        status_path(log_path).write_text(text + "\n", encoding="utf-8")

    def read_status(log_path: Path) -> dict[str, str]:
        path = status_path(log_path)
        if not path.exists():
            return {"state": "unknown", "detail": ""}
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"state": lines[0] if lines else "unknown", "detail": "\n".join(lines[1:])}

    def parse_ansible_progress(content: str) -> dict[str, object]:
        current_task = ""
        hosts: dict[str, dict[str, str]] = {}
        host_line = re.compile(r"^(ok|changed|fatal|unreachable|skipping): \[([^\]]+)\]")

        for line in content.splitlines():
            if line.startswith("TASK [") and "]" in line:
                current_task = line.removeprefix("TASK [").split("]", 1)[0]
                continue
            match = host_line.match(line)
            if match:
                state, host = match.groups()
                hosts[host] = {
                    "name": host,
                    "state": state,
                    "task": current_task,
                    "line": line,
                }

        return {
            "current_task": current_task,
            "hosts": sorted(hosts.values(), key=lambda item: item["name"]),
        }

    def list_logs(env: str) -> list[dict[str, object]]:
        log_dir = env_dir(env) / "run_logs"
        logs = []
        for path in sorted(log_dir.glob("*.log"), reverse=True)[:50]:
            status = read_status(path)
            logs.append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "status": status["state"],
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

    def latest_screenshot(env: str, host: str) -> dict[str, object] | None:
        root = env_dir(env) / "screenshots" / host
        if not root.exists():
            return None
        screenshots = sorted(root.rglob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not screenshots:
            return None
        path = screenshots[0]
        return {
            "path": path.relative_to(env_dir(env) / "screenshots").as_posix(),
            "name": path.name,
            "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }

    def capture_profile_path(env: str, host: str) -> Path:
        return env_dir(env) / "capture_profiles" / f"{host}.json"

    def load_capture_profile(env: str, host: str) -> dict[str, object] | None:
        path = capture_profile_path(env, host)
        if not path.exists():
            return None
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        for key in ("preferred_tool", "preferred_display", "preferred_auth_mode", "preferred_run_as", "runtime_user", "desktop_hint", "session_type"):
            value = profile.get(key)
            if isinstance(value, str):
                profile[key] = re.sub(r"[^A-Za-z0-9._:/-]", "", value.strip())
        return profile

    def save_capture_profile(env: str, host: str, profile: dict[str, object]) -> None:
        path = capture_profile_path(env, host)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def sanitize_capture_value(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._:/-]", "", value.strip())

    def build_screenshot_context(env: str) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
        _groups, hosts = parse_inventory(inventory_path(env))
        profiles: dict[str, dict[str, object]] = {}
        context: dict[str, dict[str, object]] = {}
        for host in hosts:
            name = str(host["name"])
            stats = load_raw_host_stats(env, name) or {}
            desktop = stats.get("desktop") or {}
            runtime_user = str(
                stats.get("runtime_user")
                or host["vars"].get("bootstrap_user")
                or host["vars"].get("ansible_user")
                or "ansible"
            )
            context[name] = {
                "runtime_user": runtime_user,
                "desktop_hint": str(desktop.get("hint") or ""),
                "session_type": str(desktop.get("session_type") or ""),
            }
            profile = load_capture_profile(env, name)
            if profile:
                profiles[name] = profile
        return profiles, context

    def display_event_path(env: str, host: str) -> Path:
        return env_dir(env) / "display_events" / f"{host}.jsonl"

    def append_display_event(env: str, host: str, event: dict[str, object]) -> None:
        path = display_event_path(env, host)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")

    def list_display_events(env: str, host: str, limit: int = 20) -> list[dict[str, object]]:
        path = display_event_path(env, host)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        events = []
        for line in lines[-limit:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(events))

    def latest_display_event(env: str, host: str) -> dict[str, object] | None:
        events = list_display_events(env, host, limit=1)
        return events[0] if events else None

    def device_event_path(env: str, host: str) -> Path:
        return env_dir(env) / "device_events" / f"{host}.jsonl"

    def append_device_event(env: str, host: str, event: dict[str, object]) -> None:
        path = device_event_path(env, host)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")

    def list_device_events(env: str, host: str, limit: int = 30) -> list[dict[str, object]]:
        path = device_event_path(env, host)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        events = []
        for line in lines[-limit:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(events))

    def latest_device_event(env: str, host: str) -> dict[str, object] | None:
        events = list_device_events(env, host, limit=1)
        return events[0] if events else None

    def analyze_png_luma(path: Path) -> dict[str, object] | None:
        data = path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return None

        offset = 8
        width = height = bit_depth = color_type = interlace = None
        palette: list[tuple[int, int, int]] = []
        idat = bytearray()

        while offset + 8 <= len(data):
            length = struct.unpack(">I", data[offset : offset + 4])[0]
            chunk_type = data[offset + 4 : offset + 8]
            chunk_data = data[offset + 8 : offset + 8 + length]
            offset += 12 + length
            if chunk_type == b"IHDR":
                width, height, bit_depth, color_type, _compression, _filter, interlace = struct.unpack(">IIBBBBB", chunk_data)
            elif chunk_type == b"PLTE":
                palette = [tuple(chunk_data[i : i + 3]) for i in range(0, len(chunk_data), 3)]
            elif chunk_type == b"IDAT":
                idat.extend(chunk_data)
            elif chunk_type == b"IEND":
                break

        if not all(value is not None for value in [width, height, bit_depth, color_type, interlace]):
            return None
        if bit_depth != 8 or interlace != 0:
            return None

        channels_by_type = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
        channels = channels_by_type.get(int(color_type))
        if channels is None:
            return None

        raw = zlib.decompress(bytes(idat))
        row_len = int(width) * channels
        previous = bytearray(row_len)
        cursor = 0
        total_luma = 0.0
        bright = 0
        samples = 0
        row_step = max(1, int(height) // 80)
        col_step = max(1, int(width) // 80)

        def paeth(left: int, up: int, up_left: int) -> int:
            estimate = left + up - up_left
            distances = (abs(estimate - left), abs(estimate - up), abs(estimate - up_left))
            if distances[0] <= distances[1] and distances[0] <= distances[2]:
                return left
            if distances[1] <= distances[2]:
                return up
            return up_left

        for y in range(int(height)):
            filter_type = raw[cursor]
            cursor += 1
            row = bytearray(raw[cursor : cursor + row_len])
            cursor += row_len
            for i in range(row_len):
                left = row[i - channels] if i >= channels else 0
                up = previous[i]
                up_left = previous[i - channels] if i >= channels else 0
                if filter_type == 1:
                    row[i] = (row[i] + left) & 0xFF
                elif filter_type == 2:
                    row[i] = (row[i] + up) & 0xFF
                elif filter_type == 3:
                    row[i] = (row[i] + ((left + up) // 2)) & 0xFF
                elif filter_type == 4:
                    row[i] = (row[i] + paeth(left, up, up_left)) & 0xFF
            previous = row

            if y % row_step != 0:
                continue
            for x in range(0, int(width), col_step):
                i = x * channels
                if color_type == 0:
                    luma = row[i]
                elif color_type == 3:
                    rgb = palette[row[i]] if row[i] < len(palette) else (0, 0, 0)
                    luma = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
                elif color_type == 4:
                    luma = row[i]
                else:
                    luma = 0.2126 * row[i] + 0.7152 * row[i + 1] + 0.0722 * row[i + 2]
                total_luma += luma
                bright += int(luma > 12)
                samples += 1

        if samples == 0:
            return None
        mean_luma = total_luma / samples
        bright_ratio = bright / samples
        return {
            "width": width,
            "height": height,
            "mean_luma": round(mean_luma, 2),
            "bright_ratio": round(bright_ratio, 4),
            "sample_count": samples,
        }

    def classify_screenshot(path: Path) -> dict[str, object]:
        size = path.stat().st_size
        analysis: dict[str, object] = {"size_bytes": size}
        try:
            png = analyze_png_luma(path)
        except Exception as exc:
            png = None
            analysis["analysis_error"] = str(exc)
        if png:
            analysis.update(png)
            is_black = float(png["mean_luma"]) < 5.0 and float(png["bright_ratio"]) < 0.005
        else:
            is_black = size < 20000
            analysis["fallback"] = "size-threshold"
        analysis["event_type"] = "screenshot_black" if is_black else "screenshot_active"
        return analysis

    def record_screenshot_events(env: str, log_path: Path, started_at: datetime) -> None:
        screenshot_root = env_dir(env) / "screenshots"
        cutoff = started_at.timestamp() - 5
        for path in screenshot_root.rglob("*.png"):
            if path.stat().st_mtime < cutoff:
                continue
            try:
                host = path.relative_to(screenshot_root).parts[0]
            except IndexError:
                continue
            analysis = classify_screenshot(path)
            append_display_event(
                env,
                host,
                {
                    "timestamp": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                    "event_type": analysis.pop("event_type"),
                    "source": "screenshot",
                    "source_log": log_path.name,
                    "screenshot_path": path.relative_to(screenshot_root).as_posix(),
                    "metadata": analysis,
                },
            )

        content = log_path.read_text(encoding="utf-8", errors="replace")
        success_re = re.compile(
            r"TRACK_CAPTURE host=(?P<host>\S+) tool=(?P<tool>\S+) display=(?P<display>\S+) auth_mode=(?P<auth_mode>\S+) run_as=(?P<run_as>\S+)"
        )
        for match in success_re.finditer(content):
            host = match.group("host")
            current = load_raw_host_stats(env, host) or {}
            desktop = current.get("desktop") or {}
            profile = load_capture_profile(env, host) or {}
            profile.update(
                {
                    "runtime_user": current.get("runtime_user") or profile.get("runtime_user"),
                    "desktop_hint": desktop.get("hint") or profile.get("desktop_hint"),
                    "session_type": desktop.get("session_type") or profile.get("session_type"),
                    "preferred_tool": sanitize_capture_value(match.group("tool")),
                    "preferred_display": sanitize_capture_value(match.group("display")),
                    "preferred_auth_mode": sanitize_capture_value(match.group("auth_mode")),
                    "preferred_run_as": sanitize_capture_value(match.group("run_as")),
                    "last_success": datetime.now().isoformat(timespec="seconds"),
                    "last_result": "success",
                }
            )
            save_capture_profile(env, host, profile)
        for host in sorted(set(re.findall(r"Screenshot failed for ([A-Za-z0-9_.:-]+)", content))):
            profile = load_capture_profile(env, host) or {}
            profile["last_failure"] = datetime.now().isoformat(timespec="seconds")
            profile["last_result"] = "failed"
            save_capture_profile(env, host, profile)
            append_display_event(
                env,
                host,
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "event_type": "screenshot_failed",
                    "source": "screenshot",
                    "source_log": log_path.name,
                    "metadata": {"reason": "capture_failed"},
                },
            )

    def host_stats_path(env: str, host: str) -> Path:
        return env_dir(env) / "stats" / host / "tmp" / "track-devicecontrol-stats.json"

    def load_host_stats(env: str, host: str) -> dict[str, object] | None:
        path = host_stats_path(env, host)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        data["_modified"] = modified.strftime("%Y-%m-%d %H:%M:%S")
        data["_age_seconds"] = int((datetime.now() - modified).total_seconds())
        return data

    def load_raw_host_stats(env: str, host: str) -> dict[str, object] | None:
        path = host_stats_path(env, host)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def snapshot_host_stats(env: str) -> dict[str, dict[str, object]]:
        _groups, hosts = parse_inventory(inventory_path(env))
        snapshot = {}
        for host in hosts:
            name = str(host["name"])
            stats = load_raw_host_stats(env, name)
            if stats is not None:
                snapshot[name] = stats
        return snapshot

    def parse_failed_hosts(content: str) -> set[str]:
        failed = set()
        for match in re.finditer(r"^(?:fatal|unreachable): \[([^\]]+)\]", content, flags=re.MULTILINE):
            failed.add(match.group(1))
        return failed

    def record_collect_stats_events(env: str, log_path: Path, started_at: datetime, previous_stats: dict[str, dict[str, object]]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        content = log_path.read_text(encoding="utf-8", errors="replace")
        for host in sorted(parse_failed_hosts(content)):
            append_device_event(
                env,
                host,
                {
                    "timestamp": now,
                    "event_type": "poll_failed",
                    "source": "collect-stats",
                    "source_log": log_path.name,
                    "metadata": {"reason": "ansible_failed_or_unreachable"},
                },
            )

        _groups, hosts = parse_inventory(inventory_path(env))
        for host_entry in hosts:
            host = str(host_entry["name"])
            path = host_stats_path(env, host)
            if not path.exists() or path.stat().st_mtime < started_at.timestamp() - 5:
                continue
            current = load_raw_host_stats(env, host)
            if current is None:
                continue
            previous = previous_stats.get(host)
            previous_event = latest_device_event(env, host)
            metadata = {
                "hostname": current.get("hostname"),
                "boot_id": current.get("boot_id"),
                "boot_time": current.get("boot_time"),
                "uptime": current.get("uptime"),
            }
            append_device_event(
                env,
                host,
                {
                    "timestamp": now,
                    "event_type": "host_seen",
                    "source": "collect-stats",
                    "source_log": log_path.name,
                    "metadata": metadata,
                },
            )
            if previous_event and previous_event.get("event_type") == "poll_failed":
                append_device_event(
                    env,
                    host,
                    {
                        "timestamp": now,
                        "event_type": "host_recovered",
                        "source": "collect-stats",
                        "source_log": log_path.name,
                        "metadata": metadata,
                    },
                )
            if previous:
                previous_boot_id = previous.get("boot_id")
                current_boot_id = current.get("boot_id")
                if previous_boot_id and current_boot_id and previous_boot_id != current_boot_id:
                    append_device_event(
                        env,
                        host,
                        {
                            "timestamp": now,
                            "event_type": "boot_id_changed",
                            "source": "collect-stats",
                            "source_log": log_path.name,
                            "metadata": {
                                "previous_boot_id": previous_boot_id,
                                "current_boot_id": current_boot_id,
                                "current_boot_time": current.get("boot_time"),
                                "uptime": current.get("uptime"),
                            },
                        },
                    )

    def device_last_seen(stats: dict[str, object] | None) -> dict[str, str]:
        if not stats:
            return {
                "label": "never",
                "state": "unknown",
                "hint": "No successful stats collection yet.",
            }
        age_seconds = int(stats.get("_age_seconds", 0))
        if age_seconds < 300:
            state = "fresh"
        elif age_seconds < 3600:
            state = "stale"
        else:
            state = "offline"

        if age_seconds < 60:
            label = "just now"
        elif age_seconds < 3600:
            label = f"{age_seconds // 60} min ago"
        elif age_seconds < 86400:
            label = f"{age_seconds // 3600} h ago"
        else:
            label = f"{age_seconds // 86400} d ago"

        return {
            "label": label,
            "state": state,
            "hint": "Last successful stats collection.",
        }

    def build_devices(env: str) -> tuple[list[str], list[dict[str, object]]]:
        groups, hosts = parse_inventory(inventory_path(env))
        devices = []
        for host in hosts:
            name = str(host["name"])
            devices.append(
                {
                    **host,
                    "screenshot": latest_screenshot(env, name),
                    "stats": load_host_stats(env, name),
                    "capture_profile": load_capture_profile(env, name),
                    "display_event": latest_display_event(env, name),
                    "display_events": list_display_events(env, name),
                    "device_event": latest_device_event(env, name),
                    "device_events": list_device_events(env, name),
                }
            )
            devices[-1]["last_seen"] = device_last_seen(devices[-1]["stats"])
        return groups, devices

    def find_device(env: str, host_name: str) -> tuple[list[str], dict[str, object] | None]:
        groups, devices = build_devices(env)
        for device in devices:
            if device["name"] == host_name:
                return groups, device
        return groups, None

    def ansible_available() -> bool:
        return shutil.which("ansible-playbook") is not None

    def run_playbook_job(
        command: list[str],
        log_path: Path,
        timeout_seconds: int,
        env: str,
        action_id: str,
        started_at: datetime,
        previous_stats: dict[str, dict[str, object]] | None = None,
        cleanup_paths: list[Path] | None = None,
    ) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            if not ansible_available():
                handle.write("ERROR: ansible-playbook was not found in PATH.\n")
                write_status(log_path, "failed", "ansible-playbook was not found in PATH.")
                return
            try:
                run_env = os.environ.copy()
                run_env["ANSIBLE_HOST_KEY_CHECKING"] = "True"
                run_env["ANSIBLE_NOCOLOR"] = "1"
                result = subprocess.run(
                    command,
                    cwd=BASE_DIR,
                    env=run_env,
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                )
                handle.write(f"\nExit code: {result.returncode}\n")
                handle.flush()
                if action_id in {"screenshot", "screenshot-setup"}:
                    record_screenshot_events(env, log_path, started_at)
                if action_id == "collect-stats":
                    record_collect_stats_events(env, log_path, started_at, previous_stats or {})
                write_status(log_path, "finished" if result.returncode == 0 else "failed", f"exit_code={result.returncode}")
            except subprocess.TimeoutExpired:
                handle.write(f"\nERROR: action timed out after {timeout_seconds} seconds.\n")
                write_status(log_path, "failed", f"timeout={timeout_seconds}")
            finally:
                for path in cleanup_paths or []:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass

    @app.context_processor
    def inject_state():
        track_base_url = app.config["TRACK_BASE_URL"]
        forwarded_host = request.headers.get("X-Forwarded-Host", "").strip()
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").strip() or request.scheme
        if forwarded_host:
            track_base_url = urlunsplit((forwarded_proto, forwarded_host, "", "", "")) or track_base_url
        return {
            "current_environment": current_environment(),
            "actions": ACTIONS,
            "ansible_available": ansible_available(),
            "csrf_token": csrf_token,
            "track_base_url": track_base_url,
        }

    @app.get("/")
    def index():
        env = current_environment()
        groups, devices = build_devices(env)
        return render_template(
            "index.html",
            environment=env,
            groups=groups,
            devices=devices,
        )

    @app.get("/mass-actions")
    def mass_actions():
        env = current_environment()
        groups, hosts = parse_inventory(inventory_path(env))
        return render_template(
            "mass_actions.html",
            environment=env,
            inventory_path=inventory_path(env),
            groups=groups,
            hosts=hosts,
            logs=list_logs(env),
            screenshots=list_screenshots(env),
            data_dir=data_dir,
        )

    @app.get("/hosts/<host_name>")
    def host_detail(host_name: str):
        env = current_environment()
        _, device = find_device(env, host_name)
        if device is None:
            abort(404)
        return render_template(
            "host.html",
            environment=env,
            device=device,
            logs=list_logs(env),
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
        cleanup_paths: list[Path] = []
        if action_id in {"screenshot", "screenshot-setup"}:
            profiles, context = build_screenshot_context(env)
            extra_vars_path = env_dir(env) / "run_logs" / f"{log_path.stem}.extra-vars.json"
            extra_vars_path.write_text(
                json.dumps(
                    {
                        "screenshot_output_dir": str(screenshot_dir),
                        "screenshot_profiles": profiles,
                        "screenshot_context": context,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            cleanup_paths.append(extra_vars_path)
            command.extend(["--extra-vars", f"@{extra_vars_path}"])
        if action_id == "collect-stats":
            command.extend(["--extra-vars", f"devicecontrol_stats_output_dir={env_dir(env) / 'stats'}"])
        previous_stats = snapshot_host_stats(env) if action_id == "collect-stats" else None

        started_at = datetime.now()
        started = started_at.strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("w", encoding="utf-8") as handle:
            handle.write(f"Started: {started}\n")
            handle.write(f"Environment: {env}\n")
            handle.write(f"Action: {action_id}\n")
            handle.write(f"Target: {target or 'all'}\n")
            handle.write(f"Command: {' '.join(shlex.quote(part) for part in command)}\n\n")
            handle.write("Status: running\n\n")
        write_status(log_path, "running")
        thread = threading.Thread(
            target=run_playbook_job,
            args=(command, log_path, timeout, env, action_id, started_at, previous_stats, cleanup_paths),
            daemon=True,
        )
        thread.start()
        return redirect(url_for("view_log", name=log_path.name))

    @app.get("/logs/<name>")
    def view_log(name: str):
        if "/" in name or name.startswith("."):
            abort(404)
        env = current_environment()
        path = env_dir(env) / "run_logs" / name
        if not path.exists():
            abort(404)
        content = path.read_text(encoding="utf-8", errors="replace")
        return render_template(
            "log.html",
            environment=env,
            name=name,
            content=content,
            status=read_status(path),
            progress=parse_ansible_progress(content),
        )

    @app.get("/screenshots/<path:name>")
    def screenshot_file(name: str):
        env = current_environment()
        root = env_dir(env) / "screenshots"
        return send_from_directory(root, name)

    return app
