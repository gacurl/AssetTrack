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
    assert b'img/curltech-badge-512.png' not in response.data
    assert b"AssetTrack by CurlTech LLC" not in response.data
    assert "🌙".encode("utf-8") in response.data
    assert b"Dark mode" in response.data
    assert b"localStorage" not in response.data
    assert b"sessionStorage" not in response.data


def test_demo_route_is_public_and_uses_demo_only_copy(client_with_temp_db) -> None:
    conn = db.get_connection()
    try:
        before = {
            "holders": int(conn.execute("SELECT COUNT(*) FROM holders;").fetchone()[0]),
            "receipts": int(conn.execute("SELECT COUNT(*) FROM receipt_queue;").fetchone()[0]),
            "events": int(conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0]),
        }
    finally:
        conn.close()

    response = client_with_temp_db.get("/demo")

    assert response.status_code == 200
    assert b"AssetTrack Demo" in response.data
    assert b"Read-Only Demo" in response.data
    assert b"This page uses sample data." in response.data
    assert b"It does not touch live records or the system of record." in response.data
    assert b"Who Has What" in response.data
    assert b"How the Workflow Stays Safe" in response.data
    assert b"Receipts, At a Glance" in response.data
    assert b"Why the Audit Trail Matters" in response.data

    conn = db.get_connection()
    try:
        after = {
            "holders": int(conn.execute("SELECT COUNT(*) FROM holders;").fetchone()[0]),
            "receipts": int(conn.execute("SELECT COUNT(*) FROM receipt_queue;").fetchone()[0]),
            "events": int(conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0]),
        }
    finally:
        conn.close()

    assert after == before


def test_demo_route_does_not_unlock_protected_operational_pages(client_with_temp_db) -> None:
    demo_response = client_with_temp_db.get("/demo")
    assert demo_response.status_code == 200

    dashboard_response = client_with_temp_db.get("/dashboard")
    holders_response = client_with_temp_db.get("/holders")
    receipts_response = client_with_temp_db.get("/receipts")

    assert dashboard_response.status_code == 403
    assert holders_response.status_code == 403
    assert receipts_response.status_code == 403


def test_demo_route_and_unauthed_protected_routes_do_not_require_db_access(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail_get_connection():
        raise AssertionError("unexpected DB access")

    monkeypatch.setattr(intake_app, "get_connection", _fail_get_connection)
    monkeypatch.setattr("assettrack.users.get_connection", _fail_get_connection)

    demo_response = client_with_temp_db.get("/demo")
    dashboard_response = client_with_temp_db.get("/dashboard")
    holders_response = client_with_temp_db.get("/holders")
    receipts_response = client_with_temp_db.get("/receipts")

    assert demo_response.status_code == 200
    assert b"AssetTrack Demo" in demo_response.data
    assert b"Safety note:" in demo_response.data

    assert dashboard_response.status_code == 403
    assert b"Access Not Allowed" in dashboard_response.data
    assert b"This page is not available with your current access." in dashboard_response.data
    assert holders_response.status_code == 403
    assert b"Access Not Allowed" in holders_response.data
    assert receipts_response.status_code == 403
    assert b"Access Not Allowed" in receipts_response.data


def test_protected_route_can_still_return_json_forbidden_when_json_is_requested(client_with_temp_db) -> None:
    response = client_with_temp_db.get("/dashboard", headers={"Accept": "application/json"})

    assert response.status_code == 403
    assert response.json == {"ok": False, "error": "Forbidden"}


def test_unknown_route_renders_friendly_404_page(client_with_temp_db) -> None:
    response = client_with_temp_db.get("/missing-page")

    assert response.status_code == 404
    assert b"Page Not Found" in response.data
    assert b"The page you requested does not exist in this AssetTrack session." in response.data


def test_unknown_route_can_still_return_json_not_found_when_json_is_requested(client_with_temp_db) -> None:
    response = client_with_temp_db.get("/missing-page", headers={"Accept": "application/json"})

    assert response.status_code == 404
    assert response.json == {"ok": False, "error": "Not Found"}


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
    assert b">Receipts</a>" in dashboard_response.data
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
    assert b">Receipts</a>" in dashboard_response.data
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
