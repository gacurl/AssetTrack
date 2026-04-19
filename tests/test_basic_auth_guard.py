# file: tests/test_basic_auth_guard.py
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

import assettrack.auth as auth
import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.users import create_user


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.close()
    intake_app.LOGIN_FAILURE_ATTEMPTS.clear()
    intake_app.ADMIN_ROUTE_ATTEMPTS.clear()
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
    with client_with_temp_db.session_transaction() as sess:
        assert "user_id" in sess
        assert "last_seen" in sess
        assert "session_started_at" in sess
        assert sess["session_started_at"] == sess["last_seen"]


def test_wrong_password_login_fails(client_with_temp_db) -> None:
    create_user("operator", "op-pass", "operator", True)
    response = _login(client_with_temp_db, "operator", "wrong")
    assert response.status_code == 403
    assert b"Invalid login" in response.data


def test_nonexistent_user_login_fails(client_with_temp_db) -> None:
    response = _login(client_with_temp_db, "missing", "pw")
    assert response.status_code == 403
    assert b"Invalid login" in response.data


def test_failed_login_attempts_accumulate_and_sixth_is_blocked(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_user("operator", "op-pass", "operator", True)
    monkeypatch.setattr(intake_app, "now_seconds", lambda: 1000)

    for _ in range(5):
        response = _login(client_with_temp_db, "operator", "wrong")
        assert response.status_code == 403
        assert b"Invalid login" in response.data

    limited = _login(client_with_temp_db, "operator", "wrong")

    assert limited.status_code == 403
    assert b"Too many login attempts. Wait and try again." in limited.data


def test_old_login_failures_outside_window_do_not_count(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_user("operator", "op-pass", "operator", True)

    monkeypatch.setattr(intake_app, "now_seconds", lambda: 1000)
    for _ in range(5):
        response = _login(client_with_temp_db, "operator", "wrong")
        assert response.status_code == 403

    monkeypatch.setattr(
        intake_app,
        "now_seconds",
        lambda: 1000 + intake_app.LOGIN_RATE_LIMIT_WINDOW_SECONDS + 1,
    )
    response = _login(client_with_temp_db, "operator", "wrong")

    assert response.status_code == 403
    assert b"Invalid login" in response.data
    assert b"Too many login attempts. Wait and try again." not in response.data


def test_successful_login_clears_failure_history(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    create_user("operator", "op-pass", "operator", True)
    monkeypatch.setattr(intake_app, "now_seconds", lambda: 1000)

    for _ in range(4):
        response = _login(client_with_temp_db, "operator", "wrong")
        assert response.status_code == 403

    success = _login(client_with_temp_db, "operator", "op-pass")
    assert success.status_code == 302

    with client_with_temp_db.session_transaction() as sess:
        sess.pop("user_id", None)
        sess.pop("last_seen", None)
        sess.pop("session_started_at", None)

    retry = _login(client_with_temp_db, "operator", "wrong")
    assert retry.status_code == 403
    assert b"Invalid login" in retry.data
    assert b"Too many login attempts. Wait and try again." not in retry.data


def test_login_screen_renders_theme_toggle_without_persistence_storage(client_with_temp_db) -> None:
    response = client_with_temp_db.get("/")
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") != "no-store"
    assert response.headers.get("Pragma") != "no-cache"
    assert response.headers.get("Expires") != "0"
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
    assert b"demo" in response.data.lower()
    assert b"sample" in response.data.lower()
    assert b"read-only" in response.data.lower()
    assert b"Safety note:" in response.data

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


def test_demo_sample_receipt_form_is_hidden_without_valid_token(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    today = intake_app.datetime.now(intake_app.timezone.utc).date()
    valid_token = f"DEMO.{today.strftime('%Y%m%d')}.EXP7"
    expired_day = today - intake_app.timedelta(days=8)
    expired_token = f"OLD.{expired_day.strftime('%Y%m%d')}.EXP7"
    monkeypatch.setenv("ASSETTRACK_DEMO_TOKENS", f"{valid_token},{expired_token}")

    plain = client_with_temp_db.get("/demo")
    invalid = client_with_temp_db.get("/demo?token=wrong")
    expired = client_with_temp_db.get(f"/demo?token={expired_token}")
    valid = client_with_temp_db.get(f"/demo?token={valid_token}")

    assert plain.status_code == 200
    assert invalid.status_code == 200
    assert expired.status_code == 200
    assert valid.status_code == 200
    assert b"Send me a sample receipt" not in plain.data
    assert b"Send me a sample receipt" not in invalid.data
    assert b"Send me a sample receipt" not in expired.data
    assert b"Send me a sample receipt" in valid.data
    assert b"Demo only. No real data." in valid.data


def test_demo_sample_receipt_send_requires_valid_token(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    today = intake_app.datetime.now(intake_app.timezone.utc).date()
    valid_token = f"DEMO.{today.strftime('%Y%m%d')}.EXP7"
    monkeypatch.setenv("ASSETTRACK_DEMO_TOKENS", valid_token)

    response = client_with_temp_db.post(
        "/demo/send-sample-receipt",
        data={"token": "wrong", "email": "demo@example.org"},
    )

    assert response.status_code == 404


def test_demo_sample_receipt_send_uses_static_demo_content_without_db_writes(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout

        def __enter__(self) -> "_FakeSMTP":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def send_message(self, message) -> None:
            captured["message"] = message

    today = intake_app.datetime.now(intake_app.timezone.utc).date()
    valid_token = f"DEMO.{today.strftime('%Y%m%d')}.EXP7"
    monkeypatch.setenv("ASSETTRACK_DEMO_TOKENS", valid_token)
    monkeypatch.setenv("ASSETTRACK_SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("ASSETTRACK_RECEIPT_FROM_EMAIL", "assettrack@example.org")
    monkeypatch.setattr(intake_app.smtplib, "SMTP", _FakeSMTP)

    conn = db.get_connection()
    try:
        before = {
            "holders": int(conn.execute("SELECT COUNT(*) FROM holders;").fetchone()[0]),
            "receipts": int(conn.execute("SELECT COUNT(*) FROM receipt_queue;").fetchone()[0]),
            "events": int(conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0]),
        }
    finally:
        conn.close()

    response = client_with_temp_db.post(
        "/demo/send-sample-receipt",
        data={"token": valid_token, "email": "demo@example.org"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Demo receipt sent to demo@example.org." in response.data
    message = captured["message"]
    assert message["Subject"] == "DEMO RECEIPT - AssetTrack sample"
    assert message["To"] == "demo@example.org"
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "DEMO RECEIPT" in body
    assert "Sample receipt only. No operational data." in body
    assert "This demo does not retain your email or any submitted data. All demo actions are stateless." in body
    assert "- LT-4421 (recorded at 2026-04-03 09:18Z)" in body
    assert "- TB-1188 (recorded at 2026-04-03 09:18Z)" in body
    assert "---" in body
    assert "This is a demo receipt generated by AssetTrack. No operational data." in body
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "AssetTrack DEMO RECEIPT.pdf"
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(attachments[0].get_payload(decode=True))).pages)
    assert "DEMO RECEIPT" in pdf_text
    assert "This demo does not retain your email or any submitted data. All demo actions are stateless." in pdf_text
    assert "LT-4421 (recorded at 2026-04-03 09:18Z)" in pdf_text
    assert "TB-1188 (recorded at 2026-04-03 09:18Z)" in pdf_text
    assert "DEMO ONLY" in pdf_text

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


def test_demo_sample_receipt_send_is_rate_limited_by_session(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    send_calls: list[str] = []

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            return None

        def __enter__(self) -> "_FakeSMTP":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def send_message(self, message) -> None:
            send_calls.append(str(message["To"]))

    today = intake_app.datetime.now(intake_app.timezone.utc).date()
    valid_token = f"DEMO.{today.strftime('%Y%m%d')}.EXP7"
    monkeypatch.setenv("ASSETTRACK_DEMO_TOKENS", valid_token)
    monkeypatch.setenv("ASSETTRACK_SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("ASSETTRACK_RECEIPT_FROM_EMAIL", "assettrack@example.org")
    monkeypatch.setattr(intake_app.smtplib, "SMTP", _FakeSMTP)

    with client_with_temp_db.session_transaction() as sess:
        sess["demo_receipt_send_count"] = 2

    response = client_with_temp_db.post(
        "/demo/send-sample-receipt",
        data={"token": valid_token, "email": "demo@example.org"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Demo send limit reached for this session." in response.data
    assert send_calls == []


def test_demo_sample_receipt_send_rejects_expired_token(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    expired_day = intake_app.datetime.now(intake_app.timezone.utc).date() - intake_app.timedelta(days=8)
    expired_token = f"DEMO.{expired_day.strftime('%Y%m%d')}.EXP7"
    monkeypatch.setenv("ASSETTRACK_DEMO_TOKENS", expired_token)

    response = client_with_temp_db.post(
        "/demo/send-sample-receipt",
        data={"token": expired_token, "email": "demo@example.org"},
    )

    assert response.status_code == 404


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
    assert b"demo" in demo_response.data.lower()
    assert b"sample" in demo_response.data.lower()
    assert b"read-only" in demo_response.data.lower()

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


def test_authenticated_json_response_sets_no_store_headers(client_with_temp_db) -> None:
    create_user("admin", "admin-pass", "admin", True)
    _login(client_with_temp_db, "admin", "admin-pass")

    response = client_with_temp_db.get("/preview/validate?json=1")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"


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
    assert dashboard_response.headers["Cache-Control"] == "no-store"
    assert dashboard_response.headers["Pragma"] == "no-cache"
    assert dashboard_response.headers["Expires"] == "0"
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


def test_authenticated_file_download_sets_no_store_headers(client_with_temp_db) -> None:
    create_user("admin", "admin-pass", "admin", True)
    _login(client_with_temp_db, "admin", "admin-pass")

    response = client_with_temp_db.get("/admin/report/pdf")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"
    assert response.headers["Content-Type"] == "application/pdf"


def test_inactive_user_login_fails(client_with_temp_db) -> None:
    create_user("inactive", "op-pass", "operator", False)
    response = _login(client_with_temp_db, "inactive", "op-pass")
    assert response.status_code == 403
    assert b"Access denied" in response.data


def test_logout_clears_auth_keys_and_preserves_workflow_state(client_with_temp_db) -> None:
    create_user("operator", "op-pass", "operator", True)
    _login(client_with_temp_db, "operator", "op-pass")
    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 41
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"

    response = client_with_temp_db.get("/logout")

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/")
    with client_with_temp_db.session_transaction() as sess:
        assert "user_id" not in sess
        assert "last_seen" not in sess
        assert "session_started_at" not in sess
        assert sess["holder_id"] == 41
        assert sess["issue_mode"] is True
        assert sess["issue_building"] == "HQ North"
        assert sess["issue_room"] == "210"


def test_authenticated_post_root_queue_action_is_not_rate_limited(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_user("operator", "op-pass", "operator", True)
    monkeypatch.setattr(intake_app, "now_seconds", lambda: 1000)
    monkeypatch.setattr(auth, "now_seconds", lambda: 1000)

    for _ in range(5):
        response = _login(client_with_temp_db, "operator", "wrong")
        assert response.status_code == 403

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = int(created["id"])
        sess["last_seen"] = 1000
        sess["session_started_at"] = 1000

    response = client_with_temp_db.post(
        "/",
        data={"action": "clear", "return_to": "/add-assets"},
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/add-assets")


def test_operator_workflow_post_root_is_unaffected_by_admin_route_rate_limit_state(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_user("operator", "op-pass", "operator", True)
    base_time = 1000
    monkeypatch.setattr(intake_app, "now_seconds", lambda: base_time)
    monkeypatch.setattr(auth, "now_seconds", lambda: base_time)
    intake_app.ADMIN_ROUTE_ATTEMPTS[f"{int(created['id'])}|admin_users_create"] = [base_time] * 10

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = int(created["id"])
        sess["last_seen"] = base_time
        sess["session_started_at"] = base_time

    response = client_with_temp_db.post(
        "/",
        data={"action": "clear", "return_to": "/add-assets"},
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/add-assets")


def test_operator_denied_admin_endpoint(client_with_temp_db) -> None:
    create_user("operator", "op-pass", "operator", True)
    _login(client_with_temp_db, "operator", "op-pass")
    response = client_with_temp_db.get("/admin/assets/new")
    assert response.status_code == 403

    retire_response = client_with_temp_db.get("/admin/assets/retire")
    assert retire_response.status_code == 403

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
    retire_response = client_with_temp_db.get("/admin/assets/retire")
    assert retire_response.status_code == 200
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
    assert b">Stage Assets</a>" not in dashboard_response.data
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
    assert b">Stage Assets</a>" in dashboard_response.data
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
