from __future__ import annotations

import sqlite3
from io import BytesIO
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
            'tablet',
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
    assert b"Admin: Tools" in response.data
    assert b'id="holder-count">1<' in response.data
    assert b'id="asset-count">1<' in response.data
    assert b"assettrack.db" in response.data
    assert b"Add Assets" not in response.data
    assert b"Users" in response.data
    assert b"Reference Data" in response.data
    assert b"Assets" in response.data
    assert b"Storage" in response.data
    assert b"Receipts and Email" in response.data
    assert b"Backup and Recovery" in response.data
    assert b"Corrections" in response.data
    assert b"Manage Users" in response.data
    assert b"Organizations and Buildings" in response.data
    assert b"Import Holders" in response.data
    assert b"Create Asset" in response.data
    assert b"Edit Asset" in response.data
    assert b"Retire Asset" in response.data
    assert b"Replace Asset" in response.data
    assert b"Import Assets" in response.data
    assert b"CSV/XLSX; Laptop, Switch, Router" in response.data
    assert response.data.count(b'href="/admin/assets/import"') == 1
    assert b"Import Switch/Router CSV" not in response.data
    assert b'href="/admin/network-assets/import"' not in response.data
    assert b"Provision Slots" in response.data
    assert b"Assign Slot" in response.data
    assert b"Move Slot" in response.data
    assert b"Receipt Search" in response.data
    assert b"Receipt CC" in response.data
    assert b"Status Report" in response.data
    assert b"Download DB Backup" in response.data
    assert b"Restore Database" in response.data
    assert b"Force Vacate Slot" in response.data
    assert b"High Risk" in response.data
    removed_descriptions = [
        b"Create accounts, assign roles, deactivate users, and issue temporary passwords.",
        b"User creation, role assignment, activation, deactivation, and temporary passwords.",
        b"Routine setup for organizations, buildings, holder records, and allowed building mappings.",
        b"Add one asset record through the guarded admin form.",
        b"Find receipts, review delivery state, and open retry or resend actions when authorized.",
        b"High-risk tools. Use only after verifying the physical state and the audit impact.",
        b"Event correction remains an amend-only protected API action",
    ]
    for removed_description in removed_descriptions:
        assert removed_description not in response.data
    expected_links = [
        b'href="/admin/users"',
        b'href="/admin/reference-data"',
        b'href="/admin/holders/import"',
        b'href="/admin/assets/new"',
        b'href="/admin/assets/edit"',
        b'href="/admin/assets/retire"',
        b'href="/admin/assets/replace"',
        b'href="/admin/assets/import"',
        b'href="/admin/slots/provision"',
        b'href="/admin/assign-slot"',
        b'href="/admin/slot-move"',
        b'href="/receipts"',
        b'href="/admin/receipt-cc"',
        b'href="/admin/report"',
        b'href="/admin/db/export"',
        b'href="/admin/db/restore"',
        b'href="/admin/force-vacate"',
    ]
    for expected_link in expected_links:
        assert expected_link in response.data
    assert response.data.count(b"<details class=\"disclosure-section") >= 3
    assert b"System Snapshot" in response.data
    assert b"Restore History" in response.data


@pytest.mark.parametrize(
    "path",
    [
        "/admin/users",
        "/admin/reference-data",
        "/admin/holders/import",
        "/admin/assets/new",
        "/admin/assets/edit",
        "/admin/assets/retire",
        "/admin/assets/replace",
        "/admin/assets/import",
        "/admin/slots/provision",
        "/admin/assign-slot",
        "/admin/slot-move",
        "/receipts",
        "/admin/receipt-cc",
        "/admin/report",
        "/admin/db/export",
        "/admin/db/restore",
        "/admin/force-vacate",
    ],
)
def test_admin_tools_link_destinations_remain_reachable_for_admin(client_with_temp_db, path: str) -> None:
    admin_id = create_test_user(username=f"admin-link-{path.replace('/', '-').strip('-')}", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    response = client_with_temp_db.get(path)

    assert response.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/admin/users",
        "/admin/reference-data",
        "/admin/holders/import",
        "/admin/assets/new",
        "/admin/assets/edit",
        "/admin/assets/retire",
        "/admin/assets/replace",
        "/admin/assets/import",
        "/admin/network-assets/import",
        "/admin/network-assets/import/template.csv",
        "/admin/slots/provision",
        "/admin/assign-slot",
        "/admin/slot-move",
        "/admin/receipt-cc",
        "/admin/report",
        "/admin/db/export",
        "/admin/db/restore",
        "/admin/force-vacate",
    ],
)
def test_admin_tools_protected_link_destinations_remain_denied_for_operator(
    client_with_temp_db,
    path: str,
) -> None:
    operator_id = create_test_user(
        username=f"operator-link-{path.replace('/', '-').strip('-')}",
        password="op-pass",
        role="operator",
    )
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get(path)

    assert response.status_code == 403


def test_operator_is_forbidden_for_system_health(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-a", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/admin/system")

    assert response.status_code == 403


def test_operator_is_forbidden_for_holder_import_page(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-import", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/admin/holders/import")

    assert response.status_code == 403


def test_admin_network_asset_import_page_is_deprecated_and_points_to_import_assets(client_with_temp_db) -> None:
    admin_id = create_test_user(username="admin-network-import", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    response = client_with_temp_db.get("/admin/network-assets/import")

    assert response.status_code == 200
    assert b"Deprecated Switch/Router CSV Import" in response.data
    assert b"deprecated for operator use" in response.data
    assert b'href="/admin/assets/import"' in response.data
    assert b"Import Assets supports CSV and XLSX files for Laptop, Switch, and Router" in response.data
    assert b"python scripts/import_network_assets_csv.py" in response.data
    assert b"network_switch_router_staging_template_v1.csv" in response.data
    assert b'href="/admin/network-assets/import/template.csv"' in response.data
    assert b"Duplicate asset tags and serial numbers are rejected" in response.data
    assert b"switch</code> or <code>router" in response.data
    assert b"No upload page is provided here" in response.data
    assert b"IP address" in response.data
    assert b"CMDB relationship" in response.data


def test_admin_network_asset_import_template_downloads_existing_csv(client_with_temp_db) -> None:
    admin_id = create_test_user(username="admin-network-template", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    response = client_with_temp_db.get("/admin/network-assets/import/template.csv")

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert b"asset_tag,barcode,serial_number,equipment_type" in response.data
    assert b"case_identifier,slot_identifier,notes_comments" in response.data


def test_admin_can_import_holders_from_csv(client_with_temp_db) -> None:
    admin_id = create_test_user(username="admin-import", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    response = client_with_temp_db.post(
        "/admin/holders/import",
        data={
            "csv_file": (
                BytesIO(b"organization,name,email\nOps Alpha,Jane Doe,jane@example.org\n"),
                "holders.csv",
            )
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Holder import complete. Processed 1 row: created 1, updated 0." in response.data
    assert b"Processed:</strong> 1" in response.data
    assert b"Created:</strong> 1" in response.data
    assert b"Updated:</strong> 0" in response.data
    assert b"Errors:</strong> 0" in response.data

    conn = db.get_connection()
    try:
        holder = conn.execute(
            "SELECT name, organization, email FROM holders WHERE email = ?;",
            ("jane@example.org",),
        ).fetchone()
    finally:
        conn.close()

    assert holder is not None
    assert dict(holder) == {"name": "Jane Doe", "organization": "Ops Alpha", "email": "jane@example.org"}


def test_admin_holder_import_page_exposes_collapsible_csv_requirements(client_with_temp_db) -> None:
    admin_id = create_test_user(username="admin-import-page", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    response = client_with_temp_db.get("/admin/holders/import")

    assert response.status_code == 200
    assert b"Holder CSV Import" in response.data
    assert b"CSV requirements" in response.data
    assert b"Columns and import behavior" in response.data
    assert b'<details class="disclosure-section">' in response.data


def test_admin_holder_import_surfaces_existing_validation_errors(client_with_temp_db) -> None:
    admin_id = create_test_user(username="admin-import-error", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    response = client_with_temp_db.post(
        "/admin/holders/import",
        data={
            "csv_file": (
                BytesIO(b"organization,name,email\nOps Alpha,,jane@example.org\n"),
                "holders.csv",
            )
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Holder import failed. Processed 1 row with 1 error." in response.data
    assert b"Row 2: name is required" in response.data

    conn = db.get_connection()
    try:
        holder_count = int(conn.execute("SELECT COUNT(*) FROM holders;").fetchone()[0])
    finally:
        conn.close()

    assert holder_count == 0


def test_operator_is_forbidden_for_human_readable_report(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-report", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/admin/report")

    assert response.status_code == 403


def test_operator_is_forbidden_for_human_readable_report_pdf(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-report-pdf", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/admin/report/pdf")

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
                'tablet',
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
    assert b"Admin: Current Status Report" in response.data
    assert b"Download PDF" in response.data
    assert b"Download Database Backup" in response.data
    assert b"Recent events:" in response.data
    assert b"active events only." in response.data
    assert b"Assets" in response.data
    assert b"Holders" in response.data
    assert b"Organizations and Building Access" in response.data
    assert b"Current Custody" in response.data
    assert b"Last 10 Events" in response.data
    assert b"Location and Case Data" in response.data
    assert response.data.count(b"<details class=\"report-section\"") >= 5
    assert b"AT-100" in response.data
    assert b"Jane Operator" in response.data
    assert b"Report Ops" in response.data
    assert b"CASE-1" in response.data
    assert b"Jan 2, 2026 12:00 AM" in response.data
    assert b"2026-01-02T00:00:00Z" not in response.data


def test_operator_report_is_actionable_with_safe_drill_in_links(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-view-report", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

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
        """,
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
                'tablet',
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
            'AT-OLD-1',
            'SN-OLD-1',
            'Dell',
            'laptop',
            'Report HQ',
            '099',
            'Latitude',
            'LAT',
            NULL,
            'Report HQ/099',
            'retired',
            'accountable',
            'unserviceable',
            '2025-12-01',
            '2026-01-01T00:00:00Z',
            'DISPOSED',
            NULL,
            NULL
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

    response = client_with_temp_db.get("/report")

    assert response.status_code == 200
    assert b"Back to Dashboard" not in response.data
    assert b'href="/dashboard">Dashboard</a>' in response.data
    assert b"Custody, Audit, Reconciliation, and Proof" in response.data
    assert b"Reports shows active custody state, audit trail, case reconciliation, and receipt support." in response.data
    assert b"Use Assets or Holders for individual lookup." in response.data
    assert b"Report Scope" not in response.data
    assert b"Holder accountability." in response.data
    assert b"Case and slot reconciliation." in response.data
    assert b"Report table links open asset proof." in response.data
    assert b"Report utilities" in response.data
    assert b"Search receipts" in response.data
    assert b"Include retired assets" in response.data
    assert response.data.count(b"<details class=\"report-section\"") >= 5
    assert b'href="/assets/search?return_to=/report"' not in response.data
    assert b'href="/dashboard/cases?return_to=/report"' not in response.data
    assert b'href="/dashboard/holders?return_to=/report"' not in response.data
    assert b'href="/receipts?return_to=/report"' in response.data
    assert b' href="/assets/search?asset_tag=AT-100&amp;return_to=/report"' in response.data
    assert b' href="/holders/1?return_to=/report"' in response.data
    assert b' href="/dashboard/cases/CASE-1?return_to=/report"' in response.data
    assert b"Last 10 Events" in response.data
    assert b"Active assets" in response.data
    assert b"1 active records" in response.data
    assert b"tablet" in response.data
    assert b"Retired hidden" in response.data
    assert b"AT-OLD-1" not in response.data
    assert b'<details class="report-section" open>' not in response.data
    assert b"Jan 2, 2026 12:00 AM" in response.data
    assert b"2026-01-02T00:00:00Z" not in response.data


def test_report_drill_ins_show_back_to_report_only_for_safe_report_context(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-report-return", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    conn = db.get_connection()
    _create_assets_table(conn)
    conn.execute(
        """
        INSERT INTO holders (id, holder_type, name, identifier, contact_info, created_at, updated_at)
        VALUES (1, 'PERSON', 'Return Holder', 'RET-1', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (10, 'CASE-RETURN', 1, 'RET-100');
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
            'RET-100',
            'SN-RET-100',
            'Dell',
            'laptop',
            'HQ',
            '100',
            'Latitude',
            'LAT',
            NULL,
            'HQ/100',
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
        WHERE asset_tag = 'RET-100';
        """
    )
    conn.commit()
    conn.close()

    asset_response = client_with_temp_db.get("/assets/search?asset_tag=RET-100&return_to=/report")
    assert asset_response.status_code == 200
    assert b'href="/report"' in asset_response.data
    assert b"Back to Report" in asset_response.data

    asset_report_filter_response = client_with_temp_db.get(
        "/assets/search?asset_tag=RET-100&return_to=/report?include_retired=1"
    )
    assert asset_report_filter_response.status_code == 200
    assert b'href="/report?include_retired=1"' in asset_report_filter_response.data
    assert b"Back to Report" in asset_report_filter_response.data

    holder_response = client_with_temp_db.get("/holders/1?return_to=/report")
    assert holder_response.status_code == 200
    assert b"Back to Report" in holder_response.data

    receipts_response = client_with_temp_db.get("/receipts?return_to=/report")
    assert receipts_response.status_code == 200
    assert b"Back to Report" in receipts_response.data
    assert b"Back to Dashboard" not in receipts_response.data
    assert b"Open Current Status Report" not in receipts_response.data

    receipts_report_filter_response = client_with_temp_db.get("/receipts?return_to=/report?include_retired=1")
    assert receipts_report_filter_response.status_code == 200
    assert b'href="/report?include_retired=1"' in receipts_report_filter_response.data
    assert b"Back to Report" in receipts_report_filter_response.data

    cases_response = client_with_temp_db.get("/dashboard/cases?return_to=/report")
    assert cases_response.status_code == 200
    assert b"Back to Report" in cases_response.data
    assert b"Back to Dashboard" not in cases_response.data
    assert b'href="/dashboard/cases/CASE-RETURN?return_to=/report"' in cases_response.data

    cases_report_filter_response = client_with_temp_db.get("/dashboard/cases?return_to=/report?include_retired=1")
    assert cases_report_filter_response.status_code == 200
    assert b'href="/report?include_retired=1"' in cases_report_filter_response.data
    assert b"Back to Report" in cases_report_filter_response.data

    case_detail_response = client_with_temp_db.get("/dashboard/cases/CASE-RETURN?return_to=/report")
    assert case_detail_response.status_code == 200
    assert b"Back to Report" in case_detail_response.data
    assert b'href="/dashboard/cases?return_to=/report"' in case_detail_response.data

    case_detail_report_filter_response = client_with_temp_db.get(
        "/dashboard/cases/CASE-RETURN?return_to=/report?include_retired=1"
    )
    assert case_detail_report_filter_response.status_code == 200
    assert b'href="/report?include_retired=1"' in case_detail_report_filter_response.data
    assert b"Back to Report" in case_detail_report_filter_response.data

    direct_asset_response = client_with_temp_db.get("/assets/search?asset_tag=RET-100")
    assert direct_asset_response.status_code == 200
    assert b"Back to Report" not in direct_asset_response.data

    direct_cases_response = client_with_temp_db.get("/dashboard/cases")
    assert direct_cases_response.status_code == 200
    assert b"Back to Dashboard" not in direct_cases_response.data
    assert b"Back to Report" not in direct_cases_response.data

    unsafe_asset_response = client_with_temp_db.get("/assets/search?asset_tag=RET-100&return_to=//evil.example")
    assert unsafe_asset_response.status_code == 200
    assert b"Back to Report" not in unsafe_asset_response.data


def test_report_recent_active_events_is_limited_to_latest_ten_and_newest_first(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-report-tail", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    conn = db.get_connection()
    _create_assets_table(conn)
    conn.execute(
        """
        INSERT INTO holders (id, holder_type, name, identifier, contact_info, created_at, updated_at)
        VALUES (1, 'PERSON', 'Tail Holder', 'TAIL-1', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    for index in range(1, 13):
        conn.execute(
            """
            INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
            VALUES (?, 'ISSUE', ?, 'system', NULL, '{"to_location_type":"IN_CUSTODY"}', 1);
            """,
            (
                f"TAIL-{index:02d}",
                f"2026-01-{index:02d}T00:00:00Z",
            ),
        )
    conn.commit()

    stored_count = conn.execute("SELECT COUNT(*) AS c FROM asset_events;").fetchone()["c"]
    conn.close()
    assert stored_count == 12

    response = client_with_temp_db.get("/report")

    assert response.status_code == 200
    assert b"Last 10 Events" in response.data
    assert response.data.find(b"TAIL-12") < response.data.find(b"TAIL-11")
    assert response.data.find(b"TAIL-11") < response.data.find(b"TAIL-10")
    assert b"TAIL-12" in response.data
    assert b"TAIL-03" in response.data
    assert b"TAIL-02" not in response.data
    assert b"TAIL-01" not in response.data
    assert b"Jan 12, 2026 12:00 AM" in response.data
    assert b"2026-01-12T00:00:00Z" not in response.data

    admin_id = create_test_user(username="admin-report-tail", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)
    admin_response = client_with_temp_db.get("/admin/report")

    assert admin_response.status_code == 200
    assert b"Last 10 Events" in admin_response.data
    assert b"TAIL-12" in admin_response.data
    assert b"TAIL-03" in admin_response.data
    assert b"TAIL-02" not in admin_response.data
    assert b"TAIL-01" not in admin_response.data
    assert b"Jan 12, 2026 12:00 AM" in admin_response.data
    assert b"2026-01-12T00:00:00Z" not in admin_response.data


def test_reports_mark_retired_assets_as_not_in_service(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-report-retired", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    conn = db.get_connection()
    _create_assets_table(conn)
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
        VALUES
            (
                'AT-LIVE-1',
                'SN-LIVE',
                'Dell',
                'laptop',
                'HQ',
                '100',
                'Latitude',
                'LAT',
                NULL,
                'HQ/100',
                'in_stock',
                'accountable',
                'serviceable',
                '2026-01-01',
                '2026-01-01T00:00:00Z',
                'STORAGE',
                NULL,
                NULL
            ),
            (
                'AT-RET-1',
                'SN-RET',
                'Dell',
                'laptop',
                'HQ',
                '200',
                'Latitude',
                'LAT',
                NULL,
                'HQ/200',
                'retired',
                'accountable',
                'unserviceable',
                '2026-01-01',
                '2026-01-02T00:00:00Z',
                'DISPOSED',
                NULL,
                NULL
            );
        """
    )
    conn.commit()
    conn.close()

    response = client_with_temp_db.get("/report")

    assert response.status_code == 200
    assert b"AT-RET-1" not in response.data
    assert b"RETIRED \xe2\x80\x94 Not in service" not in response.data
    assert b"Include retired assets" in response.data
    assert b"In storage" in response.data
    assert b"Retired / disposed" not in response.data

    full_response = client_with_temp_db.get("/report?include_retired=1")
    assert full_response.status_code == 200
    assert b"AT-RET-1" in full_response.data
    assert b"RETIRED \xe2\x80\x94 Not in service" in full_response.data
    assert b"state-badge terminal" in full_response.data
    assert b"View active inventory only" in full_response.data
    assert b"2 total records" in full_response.data
    assert full_response.data.find(b"AT-LIVE-1") < full_response.data.find(b"AT-RET-1")

    admin_id = create_test_user(username="admin-report-retired", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)
    admin_response = client_with_temp_db.get("/admin/report")

    assert admin_response.status_code == 200
    assert b"AT-RET-1" in admin_response.data
    assert b"RETIRED \xe2\x80\x94 Not in service" in admin_response.data
    assert b"state-badge terminal" in admin_response.data
    assert b"In storage" in admin_response.data
    assert b"Retired / disposed" not in admin_response.data


def test_admin_can_download_human_readable_report_pdf(client_with_temp_db) -> None:
    admin_id = create_test_user(username="admin-report-pdf", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    conn = db.get_connection()
    _create_assets_table(conn)
    conn.execute(
        """
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('PDF Ops', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.execute(
        """
        INSERT INTO buildings (name, created_at, updated_at)
        VALUES ('PDF HQ', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    organization_id = int(
        conn.execute("SELECT id FROM organizations WHERE name = 'PDF Ops' LIMIT 1;").fetchone()[0]
    )
    building_id = int(
        conn.execute("SELECT id FROM buildings WHERE name = 'PDF HQ' LIMIT 1;").fetchone()[0]
    )
    conn.execute(
        """
        INSERT INTO organization_buildings (organization_id, building_id, created_at)
        VALUES (?, ?, '2026-01-01T00:00:00Z');
        """,
        (organization_id, building_id),
    )
    conn.execute(
        """
        INSERT INTO holders (
            id, holder_type, name, organization, organization_id, identifier, contact_info, created_at, updated_at
        )
        VALUES (
            1, 'PERSON', 'PDF Operator', 'PDF Ops', ?, 'PDF-1', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
        );
        """,
        (organization_id,),
    )
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (12, 'CASE-PDF', 1, 'PDF-100');
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
            'PDF-100',
            'SN-PDF',
            'Dell',
            'laptop',
            'PDF HQ',
            '200',
            'Latitude',
            'LAT',
            NULL,
            'PDF HQ/200',
            'issued_to',
            'accountable',
            'serviceable',
            '2026-01-01',
            '2026-01-01T00:00:00Z',
            'IN_CUSTODY',
            1,
            12
        );
        """
    )
    conn.execute(
        """
        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
        SELECT 12, id, '2026-01-01T00:00:00Z'
        FROM assets
        WHERE asset_tag = 'PDF-100';
        """
    )
    conn.execute(
        """
        INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
        VALUES (
            'PDF-100',
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

    response = client_with_temp_db.get("/admin/report/pdf")

    assert response.status_code == 200
    disposition = response.headers.get("Content-Disposition") or ""
    assert "attachment;" in disposition
    assert "assettrack-human-report-" in disposition
    assert ".pdf" in disposition
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF-")
