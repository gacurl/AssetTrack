from __future__ import annotations

import base64
from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_tag TEXT NOT NULL UNIQUE,
            location_type TEXT NULL,
            current_holder_id INTEGER NULL,
            home_slot_id INTEGER NULL
        );
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(intake_app, "INTAKE_PASSCODE", None)
    intake_app.app.testing = True
    return intake_app.app.test_client()


def test_mutation_route_missing_env_returns_503(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASSETTRACK_ADMIN_USERS", raising=False)
    response = client_with_temp_db.post("/preview/discard")
    assert response.status_code == 503


def test_mutation_route_empty_env_returns_503(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSETTRACK_ADMIN_USERS", "")
    response = client_with_temp_db.post("/preview/discard")
    assert response.status_code == 503


def test_mutation_route_malformed_env_returns_503(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSETTRACK_ADMIN_USERS", "admin-without-password")
    response = client_with_temp_db.post("/preview/discard")
    assert response.status_code == 503


def test_mutation_route_without_authorization_returns_401(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSETTRACK_ADMIN_USERS", "admin:secret")
    response = client_with_temp_db.post("/preview/discard")
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == 'Basic realm="AssetTrack Admin"'


def test_mutation_route_with_invalid_credentials_returns_401(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSETTRACK_ADMIN_USERS", "admin:secret")
    response = client_with_temp_db.post(
        "/preview/discard",
        headers=_basic_auth_header("admin", "wrong"),
    )
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == 'Basic realm="AssetTrack Admin"'


def test_mutation_route_with_valid_credentials_returns_200(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSETTRACK_ADMIN_USERS", "admin:secret")
    response = client_with_temp_db.get(
        "/admin/assets/new",
        headers=_basic_auth_header("admin", "secret"),
    )
    assert response.status_code == 200


def test_dashboard_route_remains_public(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASSETTRACK_ADMIN_USERS", raising=False)
    response = client_with_temp_db.get("/dashboard")
    assert response.status_code == 200

