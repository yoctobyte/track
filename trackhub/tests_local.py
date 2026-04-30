#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import app as trackhub_app  # noqa: E402
from config import iter_launch_entries  # noqa: E402


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


@dataclass
class FakeResponse:
    content: bytes = b"local client"
    status_code: int = 200
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {"Content-Type": "text/plain"}


def authenticated_client(app, env_id: str = "testing", base_url: str = "http://localhost"):
    client = app.test_client()
    with client.session_transaction(base_url=base_url) as session:
        session["trackhub_environment"] = env_id
        session["trackhub_authenticated"] = [env_id]
    return client


def testing_apps(app):
    return next(
        env for env in app.config["TRACKHUB"]["environments"] if env.get("id") == "testing"
    )["apps"]


def test_hidden_netinventory_client_not_listed_or_proxied_on_public_host() -> None:
    app = trackhub_app.create_app()
    base_url = "https://track.example.test"
    client = authenticated_client(app, base_url=base_url)

    home = client.get("/", base_url=base_url)
    assert_true(home.status_code == 200, "public home page should render")
    assert_true(
        b"Local Laptop Tools" not in home.data,
        "localhost-only tools should not be listed on public host",
    )

    response = client.get("/env/testing", base_url=base_url)
    assert_true(response.status_code == 200, "testing environment page should render")
    assert_true(b"NetInventory Host" in response.data, "host app should remain visible")
    assert_true(
        b"NetInventory Client" not in response.data,
        "hidden client app should not be listed on public host",
    )

    response = client.get("/netinventory-client/", base_url=base_url)
    assert_true(response.status_code == 404, "hidden client app should not proxy on public host")


def test_hidden_netinventory_client_localhost_shortcut_opens_standalone() -> None:
    app = trackhub_app.create_app()

    original_request = trackhub_app.requests.request
    seen: dict[str, str] = {}

    def fake_request(**kwargs):
        seen["url"] = kwargs["url"]
        return FakeResponse()

    trackhub_app.requests.request = fake_request
    try:
        base_url = "http://127.0.0.1"
        client = authenticated_client(app, base_url=base_url)
        home = client.get("/", base_url=base_url)
        overview = client.get("/env/testing", base_url=base_url)
        response = client.get("/netinventory-client/", base_url=base_url)
    finally:
        trackhub_app.requests.request = original_request

    assert_true(home.status_code == 200, "localhost home page should render")
    assert_true(b"Local Laptop Tools" in home.data, "localhost home page should show local tools")
    assert_true(b"NetInventory Client" in home.data, "localhost home page should link NetInventory Client")
    assert_true(
        b'href="http://127.0.0.1:8889/"' in home.data,
        "localhost home shortcut should open standalone NetInventory Client",
    )
    assert_true(overview.status_code == 200, "localhost environment page should render")
    assert_true(
        b"NetInventory Client" in overview.data,
        "localhost shortcut should show hidden client app",
    )
    assert_true(
        b'href="http://127.0.0.1:8889/"' in overview.data,
        "localhost environment shortcut should open standalone NetInventory Client",
    )
    assert_true(response.status_code == 200, "manual localhost proxy path should still proxy hidden client app")
    assert_true(
        seen.get("url", "").startswith("http://127.0.0.1:8889/"),
        "localhost shortcut should target the configured local client URL",
    )


def test_visible_netinventory_client_can_proxy_for_local_hosts() -> None:
    app = trackhub_app.create_app()
    for app_item in testing_apps(app):
        if app_item.get("id") == "netinventory-client":
            app_item["visible"] = True
            app_item["autostart"] = True

    original_request = trackhub_app.requests.request
    seen: dict[str, str] = {}

    def fake_request(**kwargs):
        seen["url"] = kwargs["url"]
        return FakeResponse()

    trackhub_app.requests.request = fake_request
    try:
        base_url = "https://track.example.test"
        client = authenticated_client(app, base_url=base_url)
        response = client.get("/netinventory-client/", base_url=base_url)
    finally:
        trackhub_app.requests.request = original_request

    assert_true(response.status_code == 200, "explicitly visible client app should proxy")
    assert_true(
        seen.get("url", "").startswith("http://127.0.0.1:8889/"),
        "explicitly visible client app should target the configured local client URL",
    )


def test_quicktrack_is_listed_and_proxyable() -> None:
    app = trackhub_app.create_app()

    original_request = trackhub_app.requests.request
    seen: dict[str, str] = {}

    def fake_request(**kwargs):
        seen["url"] = kwargs["url"]
        return FakeResponse(content=b"quicktrack")

    trackhub_app.requests.request = fake_request
    try:
        base_url = "https://track.example.test"
        client = authenticated_client(app, base_url=base_url)
        overview = client.get("/env/testing", base_url=base_url)
        response = client.get("/quicktrack/", base_url=base_url)
    finally:
        trackhub_app.requests.request = original_request

    assert_true(overview.status_code == 200, "testing environment page should render")
    assert_true(b"QuickTrack" in overview.data, "QuickTrack should be listed for testing")
    assert_true(response.status_code == 200, "QuickTrack should proxy through TrackHub")
    assert_true(
        seen.get("url", "").startswith("http://127.0.0.1:5107/"),
        "QuickTrack proxy should target the configured local app URL",
    )


def test_admin_page_renders_login_and_authenticated_view() -> None:
    app = trackhub_app.create_app()
    client = app.test_client()

    login_response = client.get("/admin")
    assert_true(login_response.status_code == 200, "admin login page should render")
    assert_true(b"Admin Login" in login_response.data, "admin login form should be present")

    with client.session_transaction() as session:
        session["trackhub_admin"] = True
    admin_response = client.get("/admin")
    assert_true(admin_response.status_code == 200, "authenticated admin page should render")
    assert_true(b"Add Location" in admin_response.data, "admin location form should be present")


def test_launch_plan_starts_quicktrack_and_local_client() -> None:
    app = trackhub_app.create_app()
    launch_rows = list(iter_launch_entries(app.config["TRACKHUB"]))
    launches = {(entry["environment_id"], entry["app_id"]): entry for entry in launch_rows}
    netinventory_client = launches.get(("testing", "netinventory-client"))
    quicktrack_rows = [entry for entry in launch_rows if entry["app_id"] == "quicktrack"]

    assert_true(quicktrack_rows, "QuickTrack should have launch entries")
    assert_true(
        all(bool(entry["autostart"]) for entry in quicktrack_rows),
        "all configured QuickTrack environments should autostart",
    )
    assert_true(netinventory_client is not None, "testing NetInventory Client should have a launch entry")
    assert_true(bool(netinventory_client["autostart"]), "testing NetInventory Client should autostart")


def main() -> None:
    test_hidden_netinventory_client_not_listed_or_proxied_on_public_host()
    test_hidden_netinventory_client_localhost_shortcut_opens_standalone()
    test_visible_netinventory_client_can_proxy_for_local_hosts()
    test_quicktrack_is_listed_and_proxyable()
    test_admin_page_renders_login_and_authenticated_view()
    test_launch_plan_starts_quicktrack_and_local_client()
    print("trackhub local tests passed")


if __name__ == "__main__":
    main()
