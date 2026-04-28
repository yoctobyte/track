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

    response = client.get("/env/testing", base_url=base_url)
    assert_true(response.status_code == 200, "testing environment page should render")
    assert_true(b"NetInventory Host" in response.data, "host app should remain visible")
    assert_true(
        b"NetInventory Client" not in response.data,
        "hidden client app should not be listed on public host",
    )

    response = client.get("/netinventory-client/", base_url=base_url)
    assert_true(response.status_code == 404, "hidden client app should not proxy on public host")


def test_hidden_netinventory_client_localhost_shortcut_can_proxy() -> None:
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
        overview = client.get("/env/testing", base_url=base_url)
        response = client.get("/netinventory-client/", base_url=base_url)
    finally:
        trackhub_app.requests.request = original_request

    assert_true(overview.status_code == 200, "localhost environment page should render")
    assert_true(
        b"NetInventory Client" in overview.data,
        "localhost shortcut should show hidden client app",
    )
    assert_true(response.status_code == 200, "localhost shortcut should proxy hidden client app")
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


def main() -> None:
    test_hidden_netinventory_client_not_listed_or_proxied_on_public_host()
    test_hidden_netinventory_client_localhost_shortcut_can_proxy()
    test_visible_netinventory_client_can_proxy_for_local_hosts()
    test_quicktrack_is_listed_and_proxyable()
    print("trackhub local tests passed")


if __name__ == "__main__":
    main()
