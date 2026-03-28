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
    assert b"Open Human-Readable Report" in response.data
    assert b"Download Database Backup" in response.data


def test_operator_is_forbidden_for_system_health(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-a", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/admin/system")

    assert response.status_code == 403


def test_operator_is_forbidden_for_human_readable_report(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-report", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/admin/report")

    assert response.status_code == 403


def test_admin_can_download_database_export(client_with_temp_db) -> None:
    admin_id = create_test_user(username="admin-export", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    response = client_with_temp_db.get("/admin/db/export")

    assert response.status_code == 200
    disposition = response.headers.get("Content-Disposition") or ""
    assert "attachment;" in disposition
    assert "assettrack-backup-" in disposition
    assert ".db" in disposition
    assert len(response.data) > 0


def test_database_export_returns_clear_error_when_file_missing(
    client_with_temp_db,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    admin_id = create_test_user(username="admin-missing-export", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)
    missing_path = tmp_path / "missing-export.db"
    monkeypatch.setattr(intake_app, "_resolved_runtime_db_path", lambda: missing_path)

    response = client_with_temp_db.get("/admin/db/export")

    assert response.status_code == 404
    assert b"Database file not found." in response.data


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


def test_admin_can_open_human_readable_report_with_data_sections(client_with_temp_db) -> None:
    admin_id = create_test_user(username="admin-report", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    conn = db.get_connection()
    _create_assets_table(conn)
    conn.execute(
        """
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Report Ops', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.execute(
        """
        INSERT INTO buildings (name, created_at, updated_at)
        VALUES ('Report HQ', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    organization_id = int(
        conn.execute("SELECT id FROM organizations WHERE name = 'Report Ops' LIMIT 1;").fetchone()[0]
    )
    building_id = int(
        conn.execute("SELECT id FROM buildings WHERE name = 'Report HQ' LIMIT 1;").fetchone()[0]
    )
    conn.execute(
        """
        INSERT INTO organization_buildings (organization_id, building_id, created_at)
        VALUES (?, ?, '2026-01-01T00:00:00Z');
        """
        ,
        (organization_id, building_id),
    )
    conn.execute(
        """
        INSERT INTO holders (
            id, holder_type, name, organization, organization_id, identifier, contact_info, created_at, updated_at
        )
        VALUES (
            1, 'PERSON', 'Jane Operator', 'Report Ops', ?, 'H-1', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
        );
        """,
        (organization_id,),
    )
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (10, 'CASE-1', 1, 'AT-100');
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
            'Report HQ',
            '100',
            'Latitude',
            'LAT',
            NULL,
            'Report HQ/100',
            'issued_to',
            'accountable',
            'serviceable',
            '2026-01-01',
            '2026-01-01T00:00:00Z',
            'IN_CUSTODY',
            1,
            10
        );
        """
    )
    conn.execute(
        """
        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
        SELECT 10, id, '2026-01-01T00:00:00Z'
        FROM assets
        WHERE asset_tag = 'AT-100';
        """
    )
    conn.execute(
        """
        INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
        VALUES (
            'AT-100',
            'ISSUE',
            '2026-01-02T00:00:00Z',
            'system',
            NULL,
            '{"to_location_type":"IN_CUSTODY"}',
            1
        );
        """
    )
    conn.commit()
    conn.close()

    response = client_with_temp_db.get("/admin/report")

    assert response.status_code == 200
    assert b"Admin: Human-Readable Report" in response.data
    assert b"This page is a read-only human-readable report" in response.data
    assert b"Download Database Backup" in response.data
    assert b"showing recent active events only" in response.data
    assert b"Assets" in response.data
    assert b"Holders" in response.data
    assert b"Organizations and Building Access" in response.data
    assert b"Current Custody" in response.data
    assert b"Recent Active Events" in response.data
    assert b"Location and Case Data" in response.data
    assert b"AT-100" in response.data
    assert b"Jane Operator" in response.data
    assert b"Report Ops" in response.data
    assert b"CASE-1" in response.data
