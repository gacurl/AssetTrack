# file: tests/test_account_change_password.py
from __future__ import annotations

from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.users import get_user_by_id, verify_password
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.close()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def test_unauthenticated_user_cannot_access_change_password(client_with_temp_db) -> None:
    get_response = client_with_temp_db.get("/account/change-password")
    post_response = client_with_temp_db.post(
        "/account/change-password",
        data={
            "current_password": "whatever",
            "new_password": "VerySecure123",
            "confirm_new_password": "VerySecure123",
        },
    )

    assert get_response.status_code == 403
    assert post_response.status_code == 403


def test_authenticated_user_can_change_password_and_session_stays_valid(client_with_temp_db) -> None:
    user_id = create_test_user(username="operator-a", password="OldPassword123", role="operator")
    login_session(client_with_temp_db, user_id)

    response = client_with_temp_db.post(
        "/account/change-password",
        data={
            "current_password": "OldPassword123",
            "new_password": "NewPassword456",
            "confirm_new_password": "NewPassword456",
        },
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/account/change-password")

    updated = get_user_by_id(user_id)
    assert updated is not None
    assert verify_password(updated, "NewPassword456")
    assert not verify_password(updated, "OldPassword123")

    with client_with_temp_db.session_transaction() as sess:
        assert int(sess["user_id"]) == user_id

    holders = client_with_temp_db.get("/holders")
    assert holders.status_code == 200

    client_with_temp_db.get("/logout")
    old_login = client_with_temp_db.post("/", data={"username": "operator-a", "password": "OldPassword123"})
    new_login = client_with_temp_db.post("/", data={"username": "operator-a", "password": "NewPassword456"})
    assert old_login.status_code == 403
    assert new_login.status_code == 302


def test_wrong_current_password_fails_without_hash_change(client_with_temp_db) -> None:
    user_id = create_test_user(username="operator-a", password="OldPassword123", role="operator")
    login_session(client_with_temp_db, user_id)
    before = get_user_by_id(user_id)
    assert before is not None

    response = client_with_temp_db.post(
        "/account/change-password",
        data={
            "current_password": "wrong-password",
            "new_password": "NewPassword456",
            "confirm_new_password": "NewPassword456",
        },
    )

    assert response.status_code == 302
    after = get_user_by_id(user_id)
    assert after is not None
    assert after["password_hash"] == before["password_hash"]


def test_weak_password_fails_without_hash_change(client_with_temp_db) -> None:
    user_id = create_test_user(username="operator-a", password="OldPassword123", role="operator")
    login_session(client_with_temp_db, user_id)
    before = get_user_by_id(user_id)
    assert before is not None

    response = client_with_temp_db.post(
        "/account/change-password",
        data={
            "current_password": "OldPassword123",
            "new_password": "short1",
            "confirm_new_password": "short1",
        },
    )

    assert response.status_code == 302
    after = get_user_by_id(user_id)
    assert after is not None
    assert after["password_hash"] == before["password_hash"]


def test_confirm_mismatch_fails_without_hash_change(client_with_temp_db) -> None:
    user_id = create_test_user(username="operator-a", password="OldPassword123", role="operator")
    login_session(client_with_temp_db, user_id)
    before = get_user_by_id(user_id)
    assert before is not None

    response = client_with_temp_db.post(
        "/account/change-password",
        data={
            "current_password": "OldPassword123",
            "new_password": "NewPassword456",
            "confirm_new_password": "Mismatch789",
        },
    )

    assert response.status_code == 302
    after = get_user_by_id(user_id)
    assert after is not None
    assert after["password_hash"] == before["password_hash"]
