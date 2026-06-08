from __future__ import annotations

from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.settings import active_receipt_cc_setting, read_receipt_cc_setting
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    intake_app.SCAN_QUEUE.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def test_admin_can_view_receipt_cc_settings(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSETTRACK_RECEIPT_CC_EMAIL", "env@example.org")
    admin_id = create_test_user(username="receipt-cc-admin-view", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    response = client_with_temp_db.get("/admin/receipt-cc")

    assert response.status_code == 200
    assert b"Admin: Receipt CC Settings" in response.data
    assert b"Environment fallback" in response.data
    assert b"env@example.org" in response.data


def test_operator_cannot_access_or_modify_receipt_cc_settings(client_with_temp_db) -> None:
    operator_id = create_test_user(username="receipt-cc-operator", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    get_response = client_with_temp_db.get("/admin/receipt-cc")
    post_response = client_with_temp_db.post("/admin/receipt-cc", data={"cc_addresses": "ops@example.org"})

    assert get_response.status_code == 403
    assert post_response.status_code == 403
    assert active_receipt_cc_setting() == ""


def test_admin_can_save_valid_receipt_cc_list_and_deduplicate(client_with_temp_db) -> None:
    admin_id = create_test_user(username="receipt-cc-admin-save", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    response = client_with_temp_db.post(
        "/admin/receipt-cc",
        data={"cc_addresses": " Ops@example.org\nops@example.org, Audit@example.org "},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Receipt CC saved: ops@example.org, audit@example.org." in response.data
    assert b"Local setting" in response.data
    assert response.data.count(b"ops@example.org") >= 1
    assert b"audit@example.org" in response.data

    conn = db.get_connection()
    try:
        assert read_receipt_cc_setting(conn) == "ops@example.org\naudit@example.org"
    finally:
        conn.close()


def test_admin_invalid_receipt_cc_is_rejected_without_changing_saved_value(client_with_temp_db) -> None:
    admin_id = create_test_user(username="receipt-cc-admin-invalid", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    valid_response = client_with_temp_db.post(
        "/admin/receipt-cc",
        data={"cc_addresses": "saved@example.org"},
        follow_redirects=True,
    )
    assert valid_response.status_code == 200

    invalid_response = client_with_temp_db.post(
        "/admin/receipt-cc",
        data={"cc_addresses": "not-an-email"},
    )

    assert invalid_response.status_code == 400
    assert b"Invalid receipt CC address: not-an-email" in invalid_response.data
    conn = db.get_connection()
    try:
        assert read_receipt_cc_setting(conn) == "saved@example.org"
    finally:
        conn.close()


def test_admin_blank_save_clears_local_receipt_cc_and_restores_env_fallback(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASSETTRACK_RECEIPT_CC_EMAIL", "fallback@example.org")
    admin_id = create_test_user(username="receipt-cc-admin-clear", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    save_response = client_with_temp_db.post(
        "/admin/receipt-cc",
        data={"cc_addresses": "local@example.org"},
        follow_redirects=True,
    )
    assert save_response.status_code == 200
    assert active_receipt_cc_setting() == "local@example.org"

    clear_response = client_with_temp_db.post(
        "/admin/receipt-cc",
        data={"cc_addresses": "  "},
        follow_redirects=True,
    )

    assert clear_response.status_code == 200
    assert b"Local receipt CC cleared. Environment fallback applies when configured." in clear_response.data
    assert b"Environment fallback" in clear_response.data
    assert b"fallback@example.org" in clear_response.data
    assert active_receipt_cc_setting() == "fallback@example.org"
