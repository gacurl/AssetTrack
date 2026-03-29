# file: tests/test_basic_auth_guard.py
from __future__ import annotations

from pathlib import Path

import pytest

import assettrack.auth as auth
import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.users import create_user


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.close()
    intake_app.app.testing = True
    client = intake_app.app.test_client()
    return client


def _login(client, username: str, password: str):
    return client.post("/", data={"username": username, "password": password})


def test_active_user_login_succeeds(client_with_temp_db) -> None:
    create_user("operator", "op-pass", "operator", True)
    response = _login(client_with_temp_db, "operator", "op-pass")
    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/dashboard")


def test_wrong_password_login_fails(client_with_temp_db) -> None:
    create_user("operator", "op-pass", "operator", True)
    response = _login(client_with_temp_db, "operator", "wrong")
    assert response.status_code == 403
    assert b"Invalid login" in response.data


def test_nonexistent_user_login_fails(client_with_temp_db) -> None:
    response = _login(client_with_temp_db, "missing", "pw")
    assert response.status_code == 403
    assert b"Invalid login" in response.data


def test_login_screen_renders_theme_toggle_without_persistence_storage(client_with_temp_db) -> None:
    response = client_with_temp_db.get("/")
    assert response.status_code == 200
    assert b'id="theme-toggle"' in response.data
    assert b"assettrack_theme" in response.data
    assert b"theme-toggle-icon" in response.data
    assert "🌙".encode("utf-8") in response.data
    assert b"Dark mode" in response.data
    assert b"localStorage" not in response.data
    assert b"sessionStorage" not in response.data


def test_dark_theme_cookie_persists_across_authenticated_navigation(client_with_temp_db) -> None:
    create_user("operator", "op-pass", "operator", True)
    _login(client_with_temp_db, "operator", "op-pass")
    client_with_temp_db.set_cookie("assettrack_theme", "dark")

    dashboard_response = client_with_temp_db.get("/dashboard")
    assert dashboard_response.status_code == 200
    assert b'<html lang="en" data-theme="dark">' in dashboard_response.data
    assert b'aria-pressed="true"' in dashboard_response.data
    assert b'aria-label="Switch to light mode"' in dashboard_response.data
    assert "\u2600\ufe0f".encode("utf-8") in dashboard_response.data
    assert b"Light mode" in dashboard_response.data

    asset_search_response = client_with_temp_db.get("/assets/search")
    assert asset_search_response.status_code == 200
    assert b'<html lang="en" data-theme="dark">' in asset_search_response.data
    assert b'aria-pressed="true"' in asset_search_response.data
    assert b'aria-label="Switch to light mode"' in asset_search_response.data
    assert "\u2600\ufe0f".encode("utf-8") in asset_search_response.data
    assert b"Light mode" in asset_search_response.data


def test_inactive_user_login_fails(client_with_temp_db) -> None:
    create_user("inactive", "op-pass", "operator", False)
    response = _login(client_with_temp_db, "inactive", "op-pass")
    assert response.status_code == 403
    assert b"Access denied" in response.data


def test_operator_denied_admin_endpoint(client_with_temp_db) -> None:
    create_user("operator", "op-pass", "operator", True)
    _login(client_with_temp_db, "operator", "op-pass")
    response = client_with_temp_db.get("/admin/assets/new")
    assert response.status_code == 403

    post_response = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-NOPE",
            "serial_number": "SER-NOPE",
            "manufacturer": "Dell",
            "equipment_type": "laptop",
            "building": "HQ",
            "room": "100",
        },
    )
    assert post_response.status_code == 403

    cleanup_response = client_with_temp_db.post(
        "/admin/assets/edit",
        data={"action": "cleanup", "lookup_asset_tag": "AT-JUNK-1", "asset_tag": "AT-JUNK-1"},
    )
    assert cleanup_response.status_code == 403

    export_response = client_with_temp_db.get("/admin/db/export")
    assert export_response.status_code == 403

    reference_data_response = client_with_temp_db.get("/admin/reference-data")
    assert reference_data_response.status_code == 403

def test_admin_allowed_admin_endpoint(client_with_temp_db) -> None:
    create_user("admin", "admin-pass", "admin", True)
    _login(client_with_temp_db, "admin", "admin-pass")
    response = client_with_temp_db.get("/admin/assets/new")
    assert response.status_code == 200
    edit_response = client_with_temp_db.get("/admin/assets/edit")
    assert edit_response.status_code == 200
    reference_data_response = client_with_temp_db.get("/admin/reference-data")
    assert reference_data_response.status_code == 200


def test_asset_search_requires_login(client_with_temp_db) -> None:
    response = client_with_temp_db.get("/assets/search")
    assert response.status_code == 403


def test_preview_not_shown_in_main_navigation_but_direct_route_still_loads(client_with_temp_db) -> None:
    create_user("operator", "op-pass", "operator", True)
    _login(client_with_temp_db, "operator", "op-pass")

    dashboard_response = client_with_temp_db.get("/dashboard")
    assert dashboard_response.status_code == 200
    assert b">Preview</a>" not in dashboard_response.data
    assert b">Issue</a>" in dashboard_response.data
    assert b">Return</a>" in dashboard_response.data
    assert b">Add Assets</a>" not in dashboard_response.data
    assert b">Users</a>" not in dashboard_response.data
    assert b">Admin Tools</a>" not in dashboard_response.data

    preview_response = client_with_temp_db.get("/preview")
    assert preview_response.status_code == 200


def test_admin_navigation_shows_admin_only_actions(client_with_temp_db) -> None:
    create_user("admin", "admin-pass", "admin", True)
    _login(client_with_temp_db, "admin", "admin-pass")

    dashboard_response = client_with_temp_db.get("/dashboard")

    assert dashboard_response.status_code == 200
    assert b">Add Assets</a>" in dashboard_response.data
    assert b">Users</a>" in dashboard_response.data
    assert b">Admin Tools</a>" in dashboard_response.data


def test_bootstrap_only_when_empty(client_with_temp_db) -> None:
    bootstrap_get = client_with_temp_db.get("/bootstrap/admin")
    assert bootstrap_get.status_code == 200

    bootstrap_post = client_with_temp_db.post(
        "/bootstrap/admin",
        data={"username": "first-admin", "password": "secret", "confirm_password": "secret"},
    )
    assert bootstrap_post.status_code == 302
    assert (bootstrap_post.headers.get("Location") or "").endswith("/dashboard")

    disabled_get = client_with_temp_db.get("/bootstrap/admin")
    assert disabled_get.status_code == 403


def test_invalid_session_user_id_forces_denial(client_with_temp_db) -> None:
    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = 999999
    response = client_with_temp_db.get("/dashboard")
    assert response.status_code == 403
    with client_with_temp_db.session_transaction() as sess:
        assert "user_id" not in sess


def test_inactive_user_denied_mid_session(client_with_temp_db) -> None:
    created = create_user("operator", "op-pass", "operator", True)
    user_id = int(created["id"])
    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = user_id

    conn = db.get_connection()
    conn.execute("UPDATE users SET active = 0 WHERE id = ?;", (user_id,))
    conn.commit()
    conn.close()

    response = client_with_temp_db.get("/dashboard")
    assert response.status_code == 403
    with client_with_temp_db.session_transaction() as sess:
        assert "user_id" not in sess


def test_unexpected_role_value_is_denied(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    created = create_user("operator", "op-pass", "operator", True)
    user_id = int(created["id"])
    monkeypatch.setattr(
        auth,
        "get_user_by_id",
        lambda _uid: {"id": user_id, "username": "operator", "password_hash": "x", "role": "root", "active": 1},
    )

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = user_id
    response = client_with_temp_db.get("/dashboard")
    assert response.status_code == 403
