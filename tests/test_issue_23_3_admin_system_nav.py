from __future__ import annotations

from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.close()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def test_admin_navigation_exposes_system_health_link(client_with_temp_db) -> None:
    admin_id = create_test_user(username="admin-nav", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    response = client_with_temp_db.get("/dashboard")

    assert response.status_code == 200
    assert b'href="/admin/system"' in response.data
    assert b">Admin Tools<" in response.data
    assert response.data.index(b">Admin Tools<") < response.data.index(b">Users<")


def test_operator_navigation_hides_system_health_link(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-nav", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/dashboard")

    assert response.status_code == 200
    assert b'href="/admin/system"' not in response.data
    assert b">Admin Tools<" not in response.data
