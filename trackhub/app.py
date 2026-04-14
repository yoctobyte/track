from __future__ import annotations

from flask import Flask, abort, redirect, render_template, session, url_for

from config import load_config


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "trackhub-dev-shell"
    app.config["TRACKHUB"] = load_config()

    def hydrate_environment(env):
        hydrated = dict(env)
        apps = []
        public_base_url = str(app.config["TRACKHUB"].get("public_base_url", "")).rstrip("/")
        for item in env.get("apps", []):
            app_item = dict(item)
            public_path = str(app_item.get("public_path", "")).strip()
            local_url = str(app_item.get("local_url", "")).strip()
            if public_base_url and public_path:
                app_item["public_url"] = f"{public_base_url}{public_path}"
            else:
                app_item["public_url"] = ""
            app_item["open_url"] = local_url or app_item["public_url"]
            apps.append(app_item)
        hydrated["apps"] = apps
        return hydrated

    def environments():
        return [hydrate_environment(env) for env in app.config["TRACKHUB"]["environments"]]

    def environment_by_id(env_id: str):
        return next((env for env in environments() if env["id"] == env_id), None)

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

    return app


app = create_app()


if __name__ == "__main__":
    cfg = app.config["TRACKHUB"]
    app.run(host=cfg["bind"], port=cfg["port"], debug=False)
