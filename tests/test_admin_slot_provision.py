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


def _login_admin(client_with_temp_db) -> None:
    admin_id = create_test_user(username="admin-slots", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)


def test_admin_slot_provision_creates_new_empty_slots_for_case(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={"case_number": "CASE-P", "slot_count": "3"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Created 3 empty slots for case CASE-P (slots 1-3)." in response.data

    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT case_name, slot_position, current_asset_tag
            FROM slots
            WHERE case_name = 'CASE-P'
            ORDER BY slot_position ASC;
            """
        ).fetchall()
    finally:
        conn.close()

    assert [(row["case_name"], row["slot_position"], row["current_asset_tag"]) for row in rows] == [
        ("CASE-P", 1, None),
        ("CASE-P", 2, None),
        ("CASE-P", 3, None),
    ]


def test_admin_slot_provision_appends_slots_for_existing_case(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (10, 'CASE-P', 1, NULL), (11, 'CASE-P', 2, NULL);
        """
    )
    conn.commit()
    conn.close()

    response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={"case_number": "CASE-P", "slot_count": "2"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Created 2 empty slots for case CASE-P (slots 3-4)." in response.data

    verify_conn = db.get_connection()
    try:
        rows = verify_conn.execute(
            "SELECT slot_position FROM slots WHERE case_name = 'CASE-P' ORDER BY slot_position ASC;"
        ).fetchall()
    finally:
        verify_conn.close()
    assert [int(row["slot_position"]) for row in rows] == [1, 2, 3, 4]


def test_unslotted_storage_asset_can_be_assigned_after_slot_provision(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    provisioned = client_with_temp_db.post(
        "/admin/slots/provision",
        data={"case_number": "CASE-Q", "slot_count": "1"},
        follow_redirects=True,
    )
    assert provisioned.status_code == 200

    created = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-UNSLOT-1",
            "serial_number": "SER-UNSLOT-1",
            "manufacturer": "Dell",
            "equipment_type": "laptop",
            "building": "HQ",
            "room": "100",
        },
    )
    assert created.status_code == 302

    assigned = client_with_temp_db.post(
        "/admin/assign-slot",
        data={
            "action": "assign",
            "asset_tag": "AT-UNSLOT-1",
            "building_room": "HQ/100",
            "case_number": "CASE-Q",
            "slot_number": "1",
            "notes": "assign after provisioning",
        },
        follow_redirects=True,
    )
    assert assigned.status_code == 200
    assert b"Assigned asset AT-UNSLOT-1 to CASE-Q slot 1." in assigned.data

    case_detail = client_with_temp_db.get("/dashboard/cases/CASE-Q")
    assert case_detail.status_code == 200
    assert b"AT-UNSLOT-1" in case_detail.data

    conn = db.get_connection()
    try:
        asset_row = conn.execute(
            "SELECT id, location_type, home_slot_id, current_holder_id FROM assets WHERE asset_tag = 'AT-UNSLOT-1';"
        ).fetchone()
        occupancy_row = conn.execute(
            "SELECT slot_id FROM slot_occupancy WHERE asset_id = ?;",
            (int(asset_row["id"]),),
        ).fetchone()
        slot_row = conn.execute("SELECT current_asset_tag FROM slots WHERE case_name = 'CASE-Q' AND slot_position = 1;").fetchone()
        events = conn.execute(
            "SELECT event_type FROM asset_events WHERE asset_tag = 'AT-UNSLOT-1' ORDER BY id ASC;"
        ).fetchall()
    finally:
        conn.close()

    assert asset_row["location_type"] == "STORAGE"
    assert asset_row["current_holder_id"] is None
    assert int(asset_row["home_slot_id"]) == int(occupancy_row["slot_id"])
    assert slot_row["current_asset_tag"] == "AT-UNSLOT-1"
    assert [str(row["event_type"]) for row in events] == ["ASSET_CREATED", "SLOT_ASSIGN"]


def test_assign_slot_page_lists_unslotted_storage_assets(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    created = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-LIST-1",
            "serial_number": "SER-LIST-1",
            "manufacturer": "Dell",
            "equipment_type": "laptop",
            "building": "HQ",
            "room": "100",
        },
    )
    assert created.status_code == 302

    response = client_with_temp_db.get("/admin/assign-slot")
    assert response.status_code == 200
    assert b"Unslotted Assets" in response.data
    assert b"AT-LIST-1" in response.data
    assert b"Assign" in response.data


def test_assign_slot_page_hides_slotted_assets_from_unslotted_list(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (99, 'CASE-Z', 1, NULL);
        """
    )
    conn.commit()
    conn.close()

    created = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-SLOTTED-1",
            "serial_number": "SER-SLOTTED-1",
            "manufacturer": "Dell",
            "equipment_type": "laptop",
            "building": "HQ",
            "room": "100",
            "case_name": "CASE-Z",
            "slot_id": "99",
        },
    )
    assert created.status_code == 302

    response = client_with_temp_db.get("/admin/assign-slot")
    assert response.status_code == 200
    assert b"<code>AT-SLOTTED-1</code>" not in response.data


def test_assign_slot_page_can_select_unslotted_asset_from_list(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    created = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-SELECT-1",
            "serial_number": "SER-SELECT-1",
            "manufacturer": "Dell",
            "equipment_type": "monitor",
            "building": "HQ",
            "room": "100",
        },
    )
    assert created.status_code == 302

    response = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "lookup", "asset_tag": "AT-SELECT-1"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Asset AT-SELECT-1 is eligible for slot assignment." in response.data
    assert b'input type="hidden" name="asset_tag" value="AT-SELECT-1"' in response.data


def test_assign_slot_manual_lookup_still_works(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    created = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-MANUAL-1",
            "serial_number": "SER-MANUAL-1",
            "manufacturer": "Dell",
            "equipment_type": "laptop",
            "building": "HQ",
            "room": "100",
        },
    )
    assert created.status_code == 302

    response = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "lookup", "asset_tag": "AT-MANUAL-1"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Asset AT-MANUAL-1 is eligible for slot assignment." in response.data
