from __future__ import annotations

import json
from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")

    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Operations', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.execute(
        """
        INSERT INTO buildings (name, created_at, updated_at)
        VALUES
            ('HQ North', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
            ('Warehouse West', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    organization_row = conn.execute(
        "SELECT id FROM organizations WHERE name = 'Operations' LIMIT 1;"
    ).fetchone()
    hq_row = conn.execute(
        "SELECT id FROM buildings WHERE name = 'HQ North' LIMIT 1;"
    ).fetchone()
    assert organization_row is not None
    assert hq_row is not None
    conn.execute(
        """
        INSERT INTO organization_buildings (organization_id, building_id, created_at)
        VALUES (?, ?, '2026-01-01T00:00:00Z');
        """
        ,
        (int(organization_row["id"]), int(hq_row["id"])),
    )
    conn.execute(
        """
        INSERT INTO holders (
            id, holder_type, name, organization, organization_id, identifier, contact_info, created_at, updated_at
        )
        VALUES (
            1, 'PERSON', 'Issue Holder', 'Operations', ?, 'IH-1', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
        );
        """,
        (int(organization_row["id"]),),
    )
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (101, 'CASE-1', 1, 'ISSUE-100');
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, asset_tag, serial_number, equipment_type, manufacturer, model,
            building, room, building_room, location_type, current_holder_id, home_slot_id
        )
        VALUES (
            501, 'ISSUE-100', 'SN-1', 'laptop', 'Dell', 'Latitude',
            'Storage', 'A1', 'Storage/A1', 'STORAGE', NULL, 101
        );
        """
    )
    conn.execute(
        """
        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
        VALUES (101, 501, '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    intake_app.SCAN_QUEUE.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def _login_issue_operator(client) -> None:
    operator_id = create_test_user(username="operator-issue-location", password="op-pass", role="operator")
    with client.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True


def test_issue_scan_requires_current_location_prerequisite(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db)

    issue_page = client_with_temp_db.get("/issue")

    assert issue_page.status_code == 200
    assert b"Current Location Prerequisite" in issue_page.data
    assert b"Before scanning, set the current building and current room / area." in issue_page.data
    assert b"Scanning is blocked." in issue_page.data
    assert b"#issue-building," in issue_page.data
    assert b"max-width: 520px;" in issue_page.data
    assert b"box-sizing: border-box;" in issue_page.data
    assert b"padding: 0.6rem;" in issue_page.data
    assert b"font-size: 1rem;" in issue_page.data
    assert b"HQ North" in issue_page.data
    assert b"Warehouse West" not in issue_page.data

    scan_response = client_with_temp_db.post(
        "/",
        data={"scan_text": "ISSUE-100", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert scan_response.status_code == 200
    assert len(intake_app.SCAN_QUEUE) == 0
    assert b"Scan not added. Choose the current building. Set the current location, then scan again." in scan_response.data
    assert b"Scanning is blocked." in scan_response.data


def test_issue_commit_rejects_building_outside_selected_holder_org(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db)

    with client_with_temp_db.session_transaction() as sess:
        sess["issue_building"] = "Warehouse West"
        sess["issue_room"] = "201"

    intake_app.SCAN_QUEUE.append(intake_app.Scan.now("ISSUE-100"))

    response = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/issue")

    conn = db.get_connection()
    try:
        asset_row = conn.execute(
            "SELECT location_type, current_holder_id, building_room FROM assets WHERE id = 501 LIMIT 1;"
        ).fetchone()
    finally:
        conn.close()

    assert asset_row is not None
    assert str(asset_row["location_type"]) == "STORAGE"
    assert asset_row["current_holder_id"] is None
    assert str(asset_row["building_room"]) == "Storage/A1"


def test_issue_commit_updates_current_location_and_preserves_home_location_context(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db)

    location_response = client_with_temp_db.post(
        "/issue/location",
        data={"building": "HQ North", "room": "210"},
        follow_redirects=True,
    )
    assert location_response.status_code == 200
    assert b"Current location set to HQ North / 210." in location_response.data
    assert b"flash success" in location_response.data

    scan_response = client_with_temp_db.post(
        "/",
        data={"scan_text": "ISSUE-100", "return_to": "/issue"},
        follow_redirects=True,
    )
    assert scan_response.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["ISSUE100"]
    assert b"Ready for preview. No blocking issues found." in scan_response.data

    preview = client_with_temp_db.get("/issue/preview")
    assert preview.status_code == 200
    assert b"Current location:</strong> HQ North / 210" in preview.data
    assert b"Current location:</strong> <code>HQ North / 210</code>" in preview.data
    assert b"Home location:</strong> <code>CASE-1 / 1</code>" in preview.data
    assert b"Home location:</strong> <code>Not assigned</code>" not in preview.data

    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on"},
        follow_redirects=False,
    )

    assert commit.status_code == 302
    assert (commit.headers.get("Location") or "").endswith("/issue?issued=1")
    assert len(intake_app.SCAN_QUEUE) == 0

    conn = db.get_connection()
    try:
        asset_row = conn.execute(
            """
            SELECT location_type, current_holder_id, home_slot_id, building, room, building_room
            FROM assets
            WHERE id = 501
            LIMIT 1;
            """
        ).fetchone()
        event_row = conn.execute(
            """
            SELECT payload, holder_id
            FROM asset_events
            WHERE asset_tag = 'ISSUE-100' AND event_type = 'ISSUE'
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()
        occupancy = conn.execute(
            "SELECT 1 FROM slot_occupancy WHERE asset_id = 501 LIMIT 1;"
        ).fetchone()
    finally:
        conn.close()

    assert asset_row is not None
    assert str(asset_row["location_type"]) == "IN_CUSTODY"
    assert int(asset_row["current_holder_id"]) == 1
    assert int(asset_row["home_slot_id"]) == 101
    assert str(asset_row["building"]) == "HQ North"
    assert str(asset_row["room"]) == "210"
    assert str(asset_row["building_room"]) == "HQ North/210"
    assert occupancy is None

    assert event_row is not None
    assert int(event_row["holder_id"]) == 1
    payload = json.loads(str(event_row["payload"]))
    assert payload["from_location_type"] == "STORAGE"
    assert payload["to_location_type"] == "IN_CUSTODY"
    assert payload["from_building_room"] == "Storage/A1"
    assert payload["to_building_room"] == "HQ North/210"
    assert int(payload["home_slot_id"]) == 101
