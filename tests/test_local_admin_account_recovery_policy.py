# file: tests/test_local_admin_account_recovery_policy.py
from __future__ import annotations

from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.users import (
    change_own_password,
    get_user_by_id,
    get_user_by_username,
    is_temporary_password,
    reset_user_password,
    set_user_active,
    verify_password,
)
from tests.auth_test_utils import create_test_user


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.close()
    intake_app.ADMIN_ROUTE_ATTEMPTS.clear()
    intake_app.LOGIN_FAILURE_ATTEMPTS.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def _recover_existing_admin_account(username: str) -> dict[str, object]:
    user = get_user_by_username(username)
    if user is None:
        raise ValueError("Target account does not exist.")
    if str(user.get("role") or "").strip().lower() != "admin":
        raise ValueError("Target account is not an admin.")

    if int(user.get("active") or 0) != 1:
        user = set_user_active(int(user["id"]), True)

    reset_result = reset_user_password(int(user["id"]))
    updated = reset_result["user"]
    return {
        "user": updated,
        "temporary_password": reset_result["temporary_password"],
    }


def test_local_admin_recovery_rejects_missing_account(client_with_temp_db) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        _recover_existing_admin_account("admin")


def test_local_admin_recovery_rejects_non_admin_account(client_with_temp_db) -> None:
    create_test_user(username="operator-a", password="op-pass", role="operator")

    with pytest.raises(ValueError, match="not an admin"):
        _recover_existing_admin_account("operator-a")


def test_local_admin_recovery_reactivates_existing_admin_and_forces_password_change(client_with_temp_db) -> None:
    admin_user_id = create_test_user(username="admin", password="old-admin-pass", role="admin", active=False)
    create_test_user(username="smoke-admin", password="unknown-smoke-pass", role="admin", active=True)

    conn = db.get_connection()
    try:
        before_events = int(conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0])
        before_receipts = int(conn.execute("SELECT COUNT(*) FROM receipt_queue;").fetchone()[0])
    finally:
        conn.close()

    result = _recover_existing_admin_account("admin")

    recovered = get_user_by_id(admin_user_id)
    assert recovered is not None
    assert result["user"]["id"] == admin_user_id
    assert recovered["role"] == "admin"
    assert int(recovered["active"]) == 1
    assert is_temporary_password(recovered)
    assert not verify_password(recovered, "old-admin-pass")

    temporary_password = str(result["temporary_password"])
    assert temporary_password
    assert temporary_password not in str(recovered["password_hash"])
    assert verify_password(recovered, temporary_password)

    conn = db.get_connection()
    try:
        after_events = int(conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0])
        after_receipts = int(conn.execute("SELECT COUNT(*) FROM receipt_queue;").fetchone()[0])
    finally:
        conn.close()
    assert after_events == before_events
    assert after_receipts == before_receipts

    login_response = client_with_temp_db.post("/", data={"username": "admin", "password": temporary_password})
    assert login_response.status_code == 302

    blocked_dashboard = client_with_temp_db.get("/dashboard")
    assert blocked_dashboard.status_code == 302
    assert (blocked_dashboard.headers.get("Location") or "").endswith("/account/change-password")

    change_own_password(admin_user_id, temporary_password, "RecoveredAdmin123")
    changed = get_user_by_id(admin_user_id)
    assert changed is not None
    assert not is_temporary_password(changed)
    assert verify_password(changed, "RecoveredAdmin123")
    assert not verify_password(changed, temporary_password)
