from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    next_url = request.args.get("next") or request.form.get("next") or "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"

    if request.method == "POST":
        password = request.form.get("password", "")
        if password == current_app.config["MAP3D_PASSWORD"]:
            session.clear()
            session["authenticated"] = True
            session.permanent = True
            return redirect(next_url)
        error = "Incorrect password."

    return render_template("login.html", error=error, next_url=next_url)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
