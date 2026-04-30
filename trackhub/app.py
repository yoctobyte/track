from __future__ import annotations

import hmac
import os
import re
import secrets
from copy import deepcopy
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from requests import RequestException
from flask import Flask, Response, abort, redirect, render_template, request, session, url_for

from config import load_config, load_passwords, save_config, save_passwords


BASE_DIR = Path(__file__).resolve().parent


def load_secret_key() -> str:
    configured = os.environ.get("TRACKHUB_SECRET_KEY", "").strip()
    if configured:
        return configured
    secret_path = BASE_DIR / ".trackhub-secret-key"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(48)
    secret_path.write_text(secret + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    return secret


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = load_secret_key()
    app.config["SESSION_COOKIE_NAME"] = "trackhub_session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["TRACKHUB"] = load_config()

    def refresh_config() -> None:
        app.config["TRACKHUB"] = load_config()

    def is_loopback_request() -> bool:
        host = request.host.split(":", 1)[0].strip("[]").lower()
        return host in {"localhost", "127.0.0.1", "::1"}

    def app_is_visible(app_item) -> bool:
        if app_item.get("visible", True):
            return True
        return bool(app_item.get("local_shortcut")) and is_loopback_request()

    def hydrate_environment(env):
        hydrated = dict(env)
        apps = []
        public_base_url = str(app.config["TRACKHUB"].get("public_base_url", "")).rstrip("/")
        routing_mode = app.config["TRACKHUB"].get("routing_mode", "reverse-proxy")
        for item in env.get("apps", []):
            app_item = dict(item)
            public_path = str(app_item.get("public_path", "")).strip()
            local_url = str(app_item.get("local_url", "")).strip()
            if public_base_url and public_path:
                app_item["public_url"] = f"{public_base_url}{public_path}"
            else:
                app_item["public_url"] = ""
            if routing_mode == "app-proxy" and public_path:
                app_item["open_url"] = public_path
            else:
                app_item["open_url"] = local_url or app_item["public_url"]
            apps.append(app_item)
        hydrated["apps"] = [app_item for app_item in apps if app_is_visible(app_item)]
        hydrated["_all_apps"] = apps
        hydrated["enabled"] = bool(hydrated.get("enabled", True))
        hydrated["has_password"] = bool(str(hydrated.get("password", "")).strip())
        return hydrated

    def environments(include_disabled: bool = False):
        items = [hydrate_environment(env) for env in app.config["TRACKHUB"]["environments"]]
        if include_disabled:
            return items
        return [env for env in items if env.get("enabled", True)]

    def environment_by_id(env_id: str, include_disabled: bool = False):
        return next((env for env in environments(include_disabled=include_disabled) if env["id"] == env_id), None)

    def current_environment():
        env_id = session.get("trackhub_environment")
        return environment_by_id(env_id, include_disabled=True) if env_id else None

    def is_authenticated_for(env_id: str) -> bool:
        authenticated = set(session.get("trackhub_authenticated", []))
        return env_id in authenticated

    def remember_authenticated_environment(env_id: str) -> None:
        authenticated = set(session.get("trackhub_authenticated", []))
        authenticated.add(env_id)
        session["trackhub_authenticated"] = sorted(authenticated)
        session["trackhub_environment"] = env_id

    def is_admin_authenticated() -> bool:
        return bool(session.get("trackhub_admin"))

    def admin_password() -> str:
        passwords = load_passwords()
        return str(passwords.get("__admin__", "")).strip() or "LalaAdmin"

    def ensure_admin_access():
        if is_admin_authenticated():
            return None
        return redirect(url_for("admin", next=request.full_path.rstrip("?")))

    def ensure_environment_access(env_id: str, next_url: str):
        env = environment_by_id(env_id, include_disabled=True)
        if env is None or not env.get("enabled", True):
            abort(404)
        if is_authenticated_for(env_id):
            session["trackhub_environment"] = env_id
            return env
        return redirect(url_for("choose_location", env_id=env_id, next=next_url))

    def select_location_redirect(next_url: str):
        return redirect(url_for("choose_location", next=next_url))

    def matching_proxy_apps(path: str):
        normalized = "/" + path.lstrip("/")
        matches = []
        for env in environments():
            for item in env.get("_all_apps", env["apps"]):
                if not app_is_visible(item):
                    continue
                public_path = str(item.get("public_path", "")).rstrip("/")
                if public_path and (normalized == public_path or normalized.startswith(public_path + "/")):
                    matches.append((env, item))
        return matches

    def proxy_app_for_request_path(path: str, preferred_env_id: str = ""):
        selected_env = environment_by_id(preferred_env_id, include_disabled=True) if preferred_env_id else current_environment()
        normalized = "/" + path.lstrip("/")

        if selected_env is not None and selected_env.get("enabled", True):
            for item in selected_env.get("_all_apps", selected_env["apps"]):
                if not app_is_visible(item):
                    continue
                public_path = str(item.get("public_path", "")).rstrip("/")
                if public_path and (normalized == public_path or normalized.startswith(public_path + "/")):
                    return selected_env, item

        matches = matching_proxy_apps(path)
        if len(matches) == 1:
            return matches[0]
        return None, None

    def is_public_proxy_path(app_item, proxied_path: str):
        public_path = str(app_item.get("public_path", "")).rstrip("/")
        normalized = "/" + proxied_path.lstrip("/")
        relative = normalized[len(public_path):] if public_path and normalized.startswith(public_path) else normalized
        allowed = app_item.get("public_proxy_paths", [])
        if not isinstance(allowed, list):
            return False
        for prefix in allowed:
            prefix_text = str(prefix).strip()
            if not prefix_text:
                continue
            if not prefix_text.startswith("/"):
                prefix_text = "/" + prefix_text
            if relative == prefix_text or relative.startswith(prefix_text + "/"):
                return True
        return False

    def proxied_target_url(app_item, proxied_path: str):
        base_url = str(app_item.get("local_url", "")).rstrip("/") + "/"
        prefix = str(app_item.get("public_path", "")).rstrip("/")
        normalized = "/" + proxied_path.lstrip("/")
        suffix = normalized[len(prefix):].lstrip("/") if normalized.startswith(prefix) else ""
        target = urljoin(base_url, suffix)
        if request.query_string:
            target = f"{target}?{request.query_string.decode()}"
        return target

    def rewrite_location_header(value: str, app_item) -> str:
        if not value:
            return value
        local_url = str(app_item.get("local_url", "")).rstrip("/")
        public_path = str(app_item.get("public_path", "")).rstrip("/")
        parts = urlsplit(value)
        if value.startswith(local_url + "/"):
            return public_path + value[len(local_url):]
        if parts.scheme or value.startswith("//"):
            return value
        if public_path and (value == public_path or value.startswith(public_path + "/")):
            return value
        if value.startswith("/"):
            return public_path + value
        return f"{public_path}/{value.lstrip('/')}"

    def rewrite_html_body(content: bytes, app_item) -> bytes:
        public_path = str(app_item.get("public_path", "")).rstrip("/")
        if not public_path:
            return content
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return content

        mount = public_path.lstrip("/")

        def prefix_after_marker(source: str, marker: str) -> str:
            result = []
            pos = 0
            while True:
                idx = source.find(marker, pos)
                if idx < 0:
                    result.append(source[pos:])
                    break
                start = idx + len(marker)
                result.append(source[pos:start])
                if source.startswith(mount, start):
                    next_index = start + len(mount)
                    if next_index >= len(source) or source[next_index] in {"/", "\"", "'"}:
                        pos = start
                        continue
                result.append(f"{mount}/")
                pos = start
            return "".join(result)

        for marker in ('href="/', "href='/", 'src="/', "src='/", 'action="/', "action='/", 'fetch("/', "fetch('/", 'fetch(`/'):
            text = prefix_after_marker(text, marker)
        return text.encode("utf-8")

    def sanitize_env_id(raw: str) -> str:
        return re.sub(r"[^a-z0-9-]+", "-", raw.strip().lower()).strip("-")

    def default_apps_for_new_environment() -> list[dict[str, object]]:
        app_templates: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for env in app.config["TRACKHUB"].get("environments", []):
            for app_item in env.get("apps", []):
                app_id = str(app_item.get("id", "")).strip()
                if not app_id or app_id in seen_ids:
                    continue
                seen_ids.add(app_id)
                app_templates.append(
                    {
                        "id": app_id,
                        "name": str(app_item.get("name", app_id.title())),
                        "summary": str(app_item.get("summary", "")),
                        "local_url": "",
                        "public_path": str(app_item.get("public_path", "")),
                        "start_script": "",
                        "status": "planned",
                    }
                )
        return app_templates

    def localhost_shortcut_apps() -> list[dict[str, object]]:
        if not is_loopback_request():
            return []
        shortcuts: list[dict[str, object]] = []
        for env in environments():
            for app_item in env.get("apps", []):
                if not app_item.get("local_shortcut"):
                    continue
                public_path = str(app_item.get("public_path", "")).strip() or str(app_item.get("open_url", "")).strip()
                if not public_path:
                    continue
                shortcuts.append(
                    {
                        "env_id": env["id"],
                        "env_name": env["name"],
                        "name": app_item.get("name", app_item.get("id", "Local Tool")),
                        "summary": app_item.get("summary", ""),
                        "href": url_for("choose_location", env_id=env["id"], next=public_path),
                    }
                )
        return shortcuts

    def serialize_config_for_save() -> dict[str, object]:
        config = deepcopy(app.config["TRACKHUB"])
        clean_envs = []
        for env in config.get("environments", []):
            item = dict(env)
            item.pop("password", None)
            item.pop("has_password", None)
            clean_apps = []
            for app_item in item.get("apps", []):
                app_clean = dict(app_item)
                app_clean.pop("public_url", None)
                app_clean.pop("open_url", None)
                app_clean.pop("_all_apps", None)
                clean_apps.append(app_clean)
            item["apps"] = clean_apps
            clean_envs.append(item)
        config["environments"] = clean_envs
        return config

    def save_runtime_state(config_data: dict[str, object], passwords: dict[str, str]) -> None:
        save_config(config_data)
        save_passwords(passwords)
        refresh_config()

    @app.context_processor
    def inject_shell_state():
        return {
            "shell_environment": current_environment(),
            "shell_authenticated": sorted(session.get("trackhub_authenticated", [])),
            "shell_admin_authenticated": is_admin_authenticated(),
        }

    @app.after_request
    def add_no_cache_headers(response: Response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            title=app.config["TRACKHUB"]["title"],
            subtitle=app.config["TRACKHUB"]["subtitle"],
            public_base_url=app.config["TRACKHUB"].get("public_base_url", ""),
            routing_mode=app.config["TRACKHUB"].get("routing_mode", "reverse-proxy"),
            environments=environments(),
            current_environment=None,
            localhost_shortcuts=localhost_shortcut_apps(),
        )

    @app.route("/admin", methods=["GET", "POST"])
    def admin():
        next_url = request.values.get("next", "").strip() or url_for("admin")
        error = ""
        message = request.args.get("message", "").strip()

        if request.method == "POST" and request.form.get("action") == "login":
            password = request.form.get("password", "")
            if not hmac.compare_digest(password, admin_password()):
                error = "Incorrect admin password."
            else:
                session["trackhub_admin"] = True
                if next_url.startswith("/") and not next_url.startswith("//"):
                    return redirect(next_url)
                return redirect(url_for("admin"))

        return render_template(
            "admin.html",
            title=app.config["TRACKHUB"]["title"],
            subtitle=app.config["TRACKHUB"]["subtitle"],
            public_base_url=app.config["TRACKHUB"].get("public_base_url", ""),
            routing_mode=app.config["TRACKHUB"].get("routing_mode", "reverse-proxy"),
            environments=environments(include_disabled=True),
            current_environment=None,
            admin_authenticated=is_admin_authenticated(),
            next_url=next_url,
            error=error,
            message=message,
        )

    @app.post("/admin/save")
    def admin_save():
        gate = ensure_admin_access()
        if gate is not None:
            return gate

        config_data = serialize_config_for_save()
        envs = config_data.get("environments", [])
        passwords = load_passwords()
        action = request.form.get("action", "").strip()

        if action == "update-environment":
            env_id = request.form.get("env_id", "").strip()
            target = next((env for env in envs if str(env.get("id", "")).strip() == env_id), None)
            if target is None:
                return redirect(url_for("admin", message="Unknown location."))

            enabled = request.form.get("enabled") == "on"
            target["enabled"] = enabled
            target["badge"] = "private" if enabled else "planned"
            password = request.form.get("password", "").strip()
            if password:
                passwords[env_id] = password
            save_runtime_state(config_data, passwords)
            return redirect(url_for("admin", message=f"Saved location {env_id}."))

        if action == "add-environment":
            env_id = sanitize_env_id(request.form.get("id", ""))
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            password = request.form.get("password", "").strip()
            enabled = request.form.get("enabled") == "on"

            if not env_id or not name:
                return redirect(url_for("admin", message="New locations need both an id and a name."))
            if any(str(env.get("id", "")).strip() == env_id for env in envs):
                return redirect(url_for("admin", message=f"Location {env_id} already exists."))

            envs.append(
                {
                    "id": env_id,
                    "name": name,
                    "description": description or f"{name} environment.",
                    "badge": "private" if enabled else "planned",
                    "enabled": enabled,
                    "apps": default_apps_for_new_environment(),
                }
            )
            if password:
                passwords[env_id] = password
            save_runtime_state(config_data, passwords)
            return redirect(url_for("admin", message=f"Added location {env_id}."))

        if action == "set-admin-password":
            password = request.form.get("password", "").strip()
            if not password:
                return redirect(url_for("admin", message="Admin password cannot be empty."))
            passwords["__admin__"] = password
            save_runtime_state(config_data, passwords)
            return redirect(url_for("admin", message="Admin password updated."))

        return redirect(url_for("admin", message="No admin action applied."))

    @app.get("/admin/logout")
    def admin_logout():
        session.pop("trackhub_admin", None)
        return redirect(url_for("admin"))

    @app.route("/choose-location", methods=["GET", "POST"])
    def choose_location():
        env_id = request.values.get("env_id", "").strip()
        username = request.values.get("username", "").strip()
        if not env_id and username:
            env_id = username
        next_url = request.values.get("next", "").strip() or "/"
        error = ""
        selected_env = environment_by_id(env_id) if env_id else None

        if request.method == "POST":
            password = request.form.get("password", "")
            if selected_env is None:
                error = "Select a valid location."
            elif not selected_env.get("password"):
                error = "This location is not configured yet."
            elif not hmac.compare_digest(password, str(selected_env.get("password", ""))):
                error = "Incorrect password."
            else:
                remember_authenticated_environment(selected_env["id"])
                if next_url.startswith("/") and not next_url.startswith("//"):
                    return redirect(next_url)
                return redirect(url_for("environment_detail", env_id=selected_env["id"]))

        return render_template(
            "choose_location.html",
            title=app.config["TRACKHUB"]["title"],
            subtitle=app.config["TRACKHUB"]["subtitle"],
            public_base_url=app.config["TRACKHUB"].get("public_base_url", ""),
            routing_mode=app.config["TRACKHUB"].get("routing_mode", "reverse-proxy"),
            environments=environments(),
            current_environment=None,
            selected_env=selected_env,
            env_id=env_id,
            next_url=next_url,
            error=error,
        )

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.get("/env/<env_id>")
    def environment_detail(env_id: str):
        gate = ensure_environment_access(env_id, request.full_path.rstrip("?"))
        if not isinstance(gate, dict):
            return gate
        env = gate
        return render_template(
            "environment.html",
            title=app.config["TRACKHUB"]["title"],
            subtitle=app.config["TRACKHUB"]["subtitle"],
            public_base_url=app.config["TRACKHUB"].get("public_base_url", ""),
            routing_mode=app.config["TRACKHUB"].get("routing_mode", "reverse-proxy"),
            environments=environments(),
            current_environment=env,
        )

    @app.route("/<path:proxied_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    def proxy_subproject(proxied_path: str):
        if app.config["TRACKHUB"].get("routing_mode") != "app-proxy":
            abort(404)

        requested_env_id = request.args.get("env", "").strip()
        if not requested_env_id and current_environment() is None:
            matches = matching_proxy_apps(proxied_path)
            matched_env_ids = {env["id"] for env, _item in matches}
            if len(matched_env_ids) > 1:
                return select_location_redirect("/" + proxied_path.lstrip("/"))
        env, app_item = proxy_app_for_request_path(proxied_path, preferred_env_id=requested_env_id)
        if app_item is None or env is None:
            abort(404)
        if not is_authenticated_for(env["id"]) and not is_public_proxy_path(app_item, proxied_path):
            return select_location_redirect("/" + proxied_path.lstrip("/"))

        local_url = str(app_item.get("local_url", "")).strip()
        if not local_url:
            abort(404)

        session["trackhub_environment"] = env["id"]
        target_url = proxied_target_url(app_item, proxied_path)
        upstream_headers = {
            key: value
            for key, value in request.headers
            if key.lower() not in {"host", "content-length", "connection", "accept-encoding"}
        }
        upstream_headers["X-Forwarded-Prefix"] = str(app_item.get("public_path", "")).rstrip("/")
        upstream_headers["X-Forwarded-Proto"] = request.scheme
        upstream_headers["X-Forwarded-Host"] = request.host
        upstream_headers["X-Forwarded-For"] = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        upstream_headers["X-Trackhub-Environment"] = str(env["id"])
        upstream_headers["X-Trackhub-Authenticated"] = "true"
        try:
            upstream = requests.request(
                method=request.method,
                url=target_url,
                headers=upstream_headers,
                data=request.get_data(),
                cookies=request.cookies,
                allow_redirects=False,
                stream=True,
                timeout=60,
            )
        except RequestException as exc:
            return (
                render_template(
                    "service_unavailable.html",
                    title=app.config["TRACKHUB"]["title"],
                    subtitle=app.config["TRACKHUB"]["subtitle"],
                    public_base_url=app.config["TRACKHUB"].get("public_base_url", ""),
                    routing_mode=app.config["TRACKHUB"].get("routing_mode", "reverse-proxy"),
                    environments=environments(),
                    current_environment=env,
                    app_item=app_item,
                    target_url=target_url,
                    error_message=str(exc),
                ),
                503,
            )

        excluded_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
        downstream_headers = []
        for key, value in upstream.headers.items():
            if key.lower() in excluded_headers:
                continue
            if key.lower() == "location":
                value = rewrite_location_header(value, app_item)
            downstream_headers.append((key, value))
        content = upstream.content
        content_type = upstream.headers.get("Content-Type", "")
        if "text/html" in content_type.lower():
            content = rewrite_html_body(content, app_item)
        return Response(content, upstream.status_code, downstream_headers)

    return app


app = create_app()


if __name__ == "__main__":
    cfg = app.config["TRACKHUB"]
    app.run(host=cfg["bind"], port=cfg["port"], debug=False)
