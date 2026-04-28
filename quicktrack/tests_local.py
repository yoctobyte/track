#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
from io import BytesIO
from pathlib import Path

from app import create_app


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def with_temp_app():
    temp = tempfile.TemporaryDirectory()
    os.environ["QUICKTRACK_DATA_DIR"] = temp.name
    app = create_app()
    app.config["TESTING"] = True
    return temp, app


def test_index_renders_capture_form() -> None:
    temp, app = with_temp_app()
    try:
        response = app.test_client().get("/")
        assert_true(response.status_code == 200, "index should render")
        assert_true(b"QuickTrack" in response.data, "index should show app name")
        assert_true(b"Add GPS Location" in response.data, "index should include explicit GPS button")
        assert_true(response.data.count(b"Submit Observation") >= 3, "submit should be reachable at top, under photo, and bottom")
    finally:
        temp.cleanup()


def test_submit_stores_photo_record_and_sender_cookie() -> None:
    temp, app = with_temp_app()
    try:
        client = app.test_client()
        response = client.post(
            "/submit",
            data={
                "sender_id": "field.user",
                "description": "Panel label close-up",
                "latitude": "52.1",
                "longitude": "5.2",
                "accuracy_m": "8.5",
                "location_captured_at": "2026-04-28T20:00:00Z",
                "photo": (BytesIO(b"fake image bytes"), "panel.jpg"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert_true(response.status_code == 302, "submit should redirect after save")
        assert_true("quicktrack_sender_id=field.user" in response.headers.get("Set-Cookie", ""), "sender id should persist in cookie")

        records = sorted((Path(temp.name) / "records").glob("*.json"))
        photos = sorted((Path(temp.name) / "photos").glob("*.jpg"))
        assert_true(len(records) == 1, "one metadata record should be written")
        assert_true(len(photos) == 1, "one photo should be written")

        record = json.loads(records[0].read_text(encoding="utf-8"))
        assert_true(record["type"] == "quicktrack.photo_observation", "record type should be explicit")
        assert_true(record["sender_id"] == "field.user", "sender id should be stored")
        assert_true(record["description"] == "Panel label close-up", "description should be stored")
        assert_true(record["location"]["latitude"] == 52.1, "latitude should be stored")
        assert_true(record["location"]["longitude"] == 5.2, "longitude should be stored")
        assert_true(record["photo"]["relative_path"].startswith("photos/"), "photo path should be relative")
        assert_true(record["id"].startswith("202"), "record id should be timestamp-prefixed")
    finally:
        temp.cleanup()


def test_submit_without_location_keeps_location_null() -> None:
    temp, app = with_temp_app()
    try:
        response = app.test_client().post(
            "/submit",
            data={
                "sender_id": "laptop-1",
                "description": "",
                "photo": (BytesIO(b"fake image bytes"), "note.png"),
            },
            content_type="multipart/form-data",
        )
        assert_true(response.status_code == 302, "submit without gps should still save")
        record_path = next((Path(temp.name) / "records").glob("*.json"))
        record = json.loads(record_path.read_text(encoding="utf-8"))
        assert_true(record["location"] is None, "location should be null when gps was not requested")
    finally:
        temp.cleanup()


def test_rejects_non_photo_extension() -> None:
    temp, app = with_temp_app()
    try:
        response = app.test_client().post(
            "/submit",
            data={
                "sender_id": "field",
                "photo": (BytesIO(b"text"), "notes.txt"),
            },
            content_type="multipart/form-data",
        )
        assert_true(response.status_code == 400, "non-photo extensions should be rejected")
        assert_true(not list((Path(temp.name) / "records").glob("*.json")), "invalid upload should not write metadata")
    finally:
        temp.cleanup()


def main() -> None:
    test_index_renders_capture_form()
    test_submit_stores_photo_record_and_sender_cookie()
    test_submit_without_location_keeps_location_null()
    test_rejects_non_photo_extension()
    print("quicktrack local tests passed")


if __name__ == "__main__":
    main()
