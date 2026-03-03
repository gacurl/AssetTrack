# file: tests/test_admin_user_management.py
from __future__ import annotations

from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.users import get_user_by_id, get_user_by_username, verify_password
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.close()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def test_admin_can_view_user_table(client_with_temp_db) -> None:
    admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
    create_test_user(username="operator-a", password="op-pass", role="operator")
    login_session(client_with_temp_db, admin_user_id)

    response = client_with_temp_db.get("/admin/users")

    assert response.status_code == 200
    assert b"Admin: Users" in response.data
    assert b"operator-a" in response.data


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
