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
    cleanup_response = client_with_temp_db.post(
        "/admin/assets/edit",
        data={"action": "cleanup", "lookup_asset_tag": "AT-JUNK-1", "asset_tag": "AT-JUNK-1"},
    )
    assert cleanup_response.status_code == 403


def test_admin_allowed_admin_endpoint(client_with_temp_db) -> None:
    create_user("admin", "admin-pass", "admin", True)
    _login(client_with_temp_db, "admin", "admin-pass")
    response = client_with_temp_db.get("/admin/assets/new")
    assert response.status_code == 200
    edit_response = client_with_temp_db.get("/admin/assets/edit")
    assert edit_response.status_code == 200


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
