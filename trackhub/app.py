from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import requests
from flask import Flask, Response, abort, redirect, render_template, request, session, url_for

from config import load_config


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "trackhub-dev-shell"
    app.config["TRACKHUB"] = load_config()

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
        hydrated["apps"] = apps
        return hydrated

    def environments():
        return [hydrate_environment(env) for env in app.config["TRACKHUB"]["environments"]]

    def environment_by_id(env_id: str):
        return next((env for env in environments() if env["id"] == env_id), None)

    def proxy_app_for_request_path(path: str):
        selected_env_id = session.get("trackhub_environment")
        env = environment_by_id(selected_env_id) if selected_env_id else None
        candidate_envs = [env] if env else []
        candidate_envs.extend(item for item in environments() if not env or item["id"] != env["id"])

        normalized = "/" + path.lstrip("/")
        for candidate_env in candidate_envs:
            for item in candidate_env["apps"]:
                public_path = str(item.get("public_path", "")).rstrip("/")
                if not public_path:
                    continue
                if normalized == public_path or normalized.startswith(public_path + "/"):
                    return item
        return None

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
        if value.startswith("/"):
            return public_path + value
        return f"{public_path}/{value.lstrip('/')}"

    @app.get("/")
    def index():
        selected = session.get("trackhub_environment")
        if selected and environment_by_id(selected):
            return redirect(url_for("environment_detail", env_id=selected))
        return render_template(
            "index.html",
            title=app.config["TRACKHUB"]["title"],
            subtitle=app.config["TRACKHUB"]["subtitle"],
            public_base_url=app.config["TRACKHUB"].get("public_base_url", ""),
            routing_mode=app.config["TRACKHUB"].get("routing_mode", "reverse-proxy"),
            environments=environments(),
            current_environment=None,
        )

    @app.get("/env/<env_id>")
    def environment_detail(env_id: str):
        env = environment_by_id(env_id)
        if env is None:
            abort(404)
        session["trackhub_environment"] = env_id
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

        app_item = proxy_app_for_request_path(proxied_path)
        if app_item is None:
            abort(404)
        local_url = str(app_item.get("local_url", "")).strip()
        if not local_url:
            abort(404)

        target_url = proxied_target_url(app_item, proxied_path)
        upstream_headers = {
            key: value
            for key, value in request.headers
            if key.lower() not in {"host", "content-length", "connection", "accept-encoding"}
        }
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

        excluded_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
        downstream_headers = []
        for key, value in upstream.headers.items():
            if key.lower() in excluded_headers:
                continue
            if key.lower() == "location":
                value = rewrite_location_header(value, app_item)
            downstream_headers.append((key, value))
        return Response(upstream.content, upstream.status_code, downstream_headers)

    return app


app = create_app()


if __name__ == "__main__":
    cfg = app.config["TRACKHUB"]
    app.run(host=cfg["bind"], port=cfg["port"], debug=False)
