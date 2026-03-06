from __future__ import annotations

import sqlite3
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


def _create_assets_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_tag TEXT NOT NULL UNIQUE,
            serial_number TEXT NULL,
            manufacturer TEXT NULL,
            equipment_type TEXT NOT NULL,
            building TEXT NULL,
            room TEXT NULL,
            model TEXT NULL,
            model_code TEXT NULL,
            notes TEXT NULL,
            building_room TEXT NULL,
            custody_state TEXT NOT NULL,
            accountability_status TEXT NOT NULL,
            condition TEXT NOT NULL,
            created_date TEXT NOT NULL,
            updated_date TEXT NULL,
            location_type TEXT NULL,
            current_holder_id INTEGER NULL,
            home_slot_id INTEGER NULL
        );
        """
    )


def test_admin_can_view_system_health_counts(client_with_temp_db) -> None:
    admin_id = create_test_user(username="admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    conn = db.get_connection()
    _create_assets_table(conn)
    conn.execute(
        """
        INSERT INTO holders (id, holder_type, name, identifier, contact_info, created_at, updated_at)
        VALUES (1, 'PERSON', 'Jane Operator', NULL, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            asset_tag,
            serial_number,
            manufacturer,
            equipment_type,
            building,
            room,
            model,
            model_code,
            notes,
            building_room,
            custody_state,
            accountability_status,
            condition,
            created_date,
            updated_date,
            location_type,
            current_holder_id,
            home_slot_id
        )
        VALUES (
            'AT-100',
            'SN-100',
            'Dell',
            'laptop',
            'HQ',
            '100',
            'ModelX',
            'MX',
            NULL,
            'HQ/100',
            'in_stock',
            'accountable',
            'serviceable',
            '2026-01-01',
            '2026-01-01T00:00:00Z',
            NULL,
            NULL,
            NULL
        );
        """
    )
    conn.commit()
    conn.close()

    response = client_with_temp_db.get("/admin/system")

    assert response.status_code == 200
    assert b"Admin: System Health" in response.data
    assert b'id="holder-count">1<' in response.data
    assert b'id="asset-count">1<' in response.data
    assert b"assettrack.db" in response.data


def test_operator_is_forbidden_for_system_health(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-a", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/admin/system")

    assert response.status_code == 403


def test_system_health_renders_warning_when_assets_query_fails(
    client_with_temp_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_id = create_test_user(username="admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)
    original_connect = sqlite3.connect

    def failing_ro_connect(*args, **kwargs):
        if kwargs.get("uri") is True and args and isinstance(args[0], str) and args[0].startswith("file:"):
            raise sqlite3.Error("boom")
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(intake_app.sqlite3, "connect", failing_ro_connect)

    response = client_with_temp_db.get("/admin/system")

    assert response.status_code == 200
    assert b"Could not read system health data:" in response.data
    assert b'id="asset-count">N/A<' in response.data
