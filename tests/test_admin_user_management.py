# file: tests/test_admin_user_management.py
from __future__ import annotations

from pathlib import Path

import pytest

import assettrack.auth as auth
import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.users import get_user_by_id, get_user_by_username, verify_password
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.close()
    intake_app.ADMIN_ROUTE_ATTEMPTS.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def test_admin_can_view_user_table(client_with_temp_db) -> None:
    admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
    operator_id = create_test_user(username="operator-a", password="op-pass", role="operator")
    conn = db.get_connection()
    try:
        conn.execute(
            """
            UPDATE users
            SET created_at = ?, updated_at = ?
            WHERE id = ?;
            """,
            ("2026-04-05T13:15:00+00:00", "2026-04-06T09:45:00+00:00", operator_id),
        )
        conn.commit()
    finally:
        conn.close()
    login_session(client_with_temp_db, admin_user_id)

    response = client_with_temp_db.get("/admin/users")

    assert response.status_code == 200
    assert b"Admin: Users" in response.data
    assert b"operator-a" in response.data
    assert b"Apr 5, 2026 at 13:15 UTC" in response.data
    assert b"Apr 6, 2026 at 09:45 UTC" in response.data
    assert b"2026-04-05T13:15:00+00:00" not in response.data
    assert b"2026-04-06T09:45:00+00:00" not in response.data


def test_admin_users_page_formats_microsecond_timestamps(client_with_temp_db) -> None:
    admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
    target_user_id = create_test_user(username="operator-b", password="op-pass", role="operator")
    stored_user = get_user_by_id(target_user_id)
    assert stored_user is not None
    raw_created_at = str(stored_user["created_at"])
    raw_updated_at = str(stored_user["updated_at"])
    assert "." in raw_created_at
    assert "." in raw_updated_at
    login_session(client_with_temp_db, admin_user_id)

    response = client_with_temp_db.get("/admin/users")

    assert response.status_code == 200
    assert raw_created_at.encode("utf-8") not in response.data
    assert raw_updated_at.encode("utf-8") not in response.data
    assert intake_app._receipt_display_timestamp(raw_created_at).encode("utf-8") in response.data
    assert intake_app._receipt_display_timestamp(raw_updated_at).encode("utf-8") in response.data


def test_admin_can_create_operator_user(client_with_temp_db) -> None:
    admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_user_id)

    response = client_with_temp_db.post(
        "/admin/users/create",
        data={"username": "new-operator", "password": "new-pass", "role": "operator", "active": "1"},
    )

    assert response.status_code == 302
    created = get_user_by_username("new-operator")
    assert created is not None
    assert created["role"] == "operator"
    assert int(created["active"]) == 1
    assert str(created["password_hash"]).startswith("scrypt:")


def test_admin_can_toggle_active_for_non_last_admin(client_with_temp_db) -> None:
    admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
    target_user_id = create_test_user(username="operator-a", password="op-pass", role="operator")
    login_session(client_with_temp_db, admin_user_id)

    response = client_with_temp_db.post(f"/admin/users/{target_user_id}/toggle-active", data={"active": "0"})

    assert response.status_code == 302
    updated = get_user_by_id(target_user_id)
    assert updated is not None
    assert int(updated["active"]) == 0


def test_admin_cannot_deactivate_last_active_admin(client_with_temp_db) -> None:
    admin_user_id = create_test_user(username="solo-admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_user_id)

    response = client_with_temp_db.post(f"/admin/users/{admin_user_id}/toggle-active", data={"active": "0"})

    assert response.status_code == 302
    updated = get_user_by_id(admin_user_id)
    assert updated is not None
    assert int(updated["active"]) == 1



def test_admin_can_reset_password_and_new_password_allows_login(client_with_temp_db) -> None:
    admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
    target_username = "operator-a"
    target_user_id = create_test_user(username=target_username, password="old-pass", role="operator")
    login_session(client_with_temp_db, admin_user_id)

    response = client_with_temp_db.post(
        f"/admin/users/{target_user_id}/reset-password",
        data={"new_password": "new-pass-123"},
    )

    assert response.status_code == 302

    client_with_temp_db.get("/logout")

    old_login = client_with_temp_db.post("/", data={"username": target_username, "password": "old-pass"})
    assert old_login.status_code == 403

    new_login = client_with_temp_db.post("/", data={"username": target_username, "password": "new-pass-123"})
    assert new_login.status_code == 302
    updated = get_user_by_id(target_user_id)
    assert updated is not None
    assert verify_password(updated, "new-pass-123")
    assert str(updated["password_hash"]).startswith("scrypt:")


def test_admin_can_change_role_and_persists(client_with_temp_db) -> None:
    admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
    target_user_id = create_test_user(username="operator-a", password="op-pass", role="operator")
    login_session(client_with_temp_db, admin_user_id)

    response = client_with_temp_db.post(
        f"/admin/users/{target_user_id}/set-role",
        data={"role": "admin"},
    )

    assert response.status_code == 302
    updated = get_user_by_id(target_user_id)
    assert updated is not None
    assert updated["role"] == "admin"


def test_admin_cannot_demote_last_active_admin(client_with_temp_db) -> None:
    admin_user_id = create_test_user(username="solo-admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_user_id)

    response = client_with_temp_db.post(
        f"/admin/users/{admin_user_id}/set-role",
        data={"role": "operator"},
    )

    assert response.status_code == 302
    updated = get_user_by_id(admin_user_id)
    assert updated is not None
    assert updated["role"] == "admin"


def test_operator_is_forbidden_for_admin_user_routes(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-a", password="op-pass", role="operator")
    target_id = create_test_user(username="target", password="target-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    assert client_with_temp_db.get("/admin/users").status_code == 403
    assert client_with_temp_db.post(
        "/admin/users/create",
        data={"username": "x", "password": "y", "role": "operator"},
    ).status_code == 403
    assert client_with_temp_db.post(f"/admin/users/{target_id}/toggle-active", data={"active": "0"}).status_code == 403
    assert client_with_temp_db.post(
        f"/admin/users/{target_id}/reset-password",
        data={"new_password": "new-pass"},
    ).status_code == 403
    assert client_with_temp_db.post(f"/admin/users/{target_id}/set-role", data={"role": "admin"}).status_code == 403


def test_admin_user_create_rate_limit_blocks_when_threshold_is_exceeded(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_user_id)
    base_time = auth.now_seconds()
    monkeypatch.setattr(auth, "now_seconds", lambda: base_time)
    monkeypatch.setattr(intake_app, "now_seconds", lambda: base_time)
    intake_app.ADMIN_ROUTE_ATTEMPTS[f"{admin_user_id}|admin_users_create"] = [base_time] * 10

    response = client_with_temp_db.post(
        "/admin/users/create",
        data={"username": "blocked-user", "password": "new-pass", "role": "operator", "active": "1"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Too many requests. Wait and try again." in response.data
    assert get_user_by_username("blocked-user") is None


def test_admin_route_rate_limit_is_endpoint_scoped_and_non_target_post_is_unaffected(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_user_id)
    base_time = auth.now_seconds()
    monkeypatch.setattr(auth, "now_seconds", lambda: base_time)
    monkeypatch.setattr(intake_app, "now_seconds", lambda: base_time)
    intake_app.ADMIN_ROUTE_ATTEMPTS[f"{admin_user_id}|admin_users_create"] = [base_time] * 10

    response = client_with_temp_db.post(
        "/admin/reference-data",
        data={"action": "create_organization", "organization_name": "Operations"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Created organization." in response.data


def test_admin_event_correction_rate_limit_returns_429_json(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_user_id)
    base_time = auth.now_seconds()
    monkeypatch.setattr(auth, "now_seconds", lambda: base_time)
    monkeypatch.setattr(intake_app, "now_seconds", lambda: base_time)
    intake_app.ADMIN_ROUTE_ATTEMPTS[f"{admin_user_id}|admin_correct_event"] = [base_time] * 10

    response = client_with_temp_db.post("/admin/events/correct", json={})

    assert response.status_code == 429
    assert response.json == {"ok": False, "error": "Too many requests. Wait and try again."}


def test_admin_route_rate_limit_prunes_old_timestamps(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_user_id)
    base_time = auth.now_seconds()
    monkeypatch.setattr(auth, "now_seconds", lambda: base_time)
    monkeypatch.setattr(intake_app, "now_seconds", lambda: base_time)
    rate_limit_key = f"{admin_user_id}|admin_users_create"
    intake_app.ADMIN_ROUTE_ATTEMPTS[rate_limit_key] = [
        base_time - intake_app.ADMIN_ROUTE_RATE_LIMIT_WINDOW_SECONDS - 1
    ] * 10

    response = client_with_temp_db.post(
        "/admin/users/create",
        data={"username": "", "password": "new-pass", "role": "operator", "active": "1"},
    )

    assert response.status_code == 302
    assert len(intake_app.ADMIN_ROUTE_ATTEMPTS[rate_limit_key]) == 1
