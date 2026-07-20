from __future__ import annotations

import json
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


def _create_building(name: str) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO buildings (name, created_at, updated_at)
            VALUES (?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """,
            (name,),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_slot_move_fixture(
    *,
    asset_tag: str = "MOVE-100",
    equipment_type: str = "switch",
    location_type: str = "STORAGE",
    source_slot_id: int = 810,
    destination_slot_id: int = 811,
    destination_occupied: bool = False,
    current_holder_id: int | None = None,
) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES
                (?, 'CASE-SRC', 1, ?),
                (?, 'CASE-DST', 2, ?);
            """,
            (
                source_slot_id,
                asset_tag,
                destination_slot_id,
                "OTHER-DEST" if destination_occupied else None,
            ),
        )
        cursor = conn.execute(
            """
            INSERT INTO assets (
                asset_tag,
                serial_number,
                equipment_type,
                manufacturer,
                model,
                building,
                room,
                building_room,
                custody_state,
                accountability_status,
                condition,
                created_date,
                updated_date,
                location_type,
                current_holder_id,
                home_slot_id,
                case_number,
                slot_number
            )
            VALUES (?, 'SER-MOVE-100', ?, 'Cisco', 'Catalyst', 'SRC', '101', 'SRC/101',
                    'in_stock', 'accountable', 'serviceable', '2026-01-01', '2026-01-01T00:00:00Z',
                    ?, ?, ?, 'CASE-SRC', '1');
            """,
            (asset_tag, equipment_type, location_type, current_holder_id, source_slot_id),
        )
        asset_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (?, ?, '2026-01-01T00:00:00Z');
            """,
            (source_slot_id, asset_id),
        )
        if destination_occupied:
            other_cursor = conn.execute(
                """
                INSERT INTO assets (
                    asset_tag,
                    serial_number,
                    equipment_type,
                    manufacturer,
                    building,
                    room,
                    building_room,
                    custody_state,
                    accountability_status,
                    condition,
                    created_date,
                    updated_date,
                    location_type,
                    current_holder_id,
                    home_slot_id,
                    case_number,
                    slot_number
                )
                VALUES ('OTHER-DEST', 'SER-OTHER-DEST', 'router', 'Cisco', 'DST', '202', 'DST/202',
                        'in_stock', 'accountable', 'serviceable', '2026-01-01', '2026-01-01T00:00:00Z',
                        'STORAGE', NULL, ?, 'CASE-DST', '2');
                """,
                (destination_slot_id,),
            )
            conn.execute(
                """
                INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
                VALUES (?, ?, '2026-01-01T00:00:00Z');
                """,
                (destination_slot_id, int(other_cursor.lastrowid)),
            )
        conn.commit()
    finally:
        conn.close()


def _slot_move_state(asset_tag: str = "MOVE-100") -> dict[str, object]:
    conn = db.get_connection()
    try:
        asset = conn.execute(
            """
            SELECT id, location_type, current_holder_id, home_slot_id, building, room, building_room, case_number, slot_number
            FROM assets
            WHERE asset_tag = ?;
            """,
            (asset_tag,),
        ).fetchone()
        source_slot = conn.execute("SELECT current_asset_tag FROM slots WHERE id = 810;").fetchone()
        destination_slot = conn.execute("SELECT current_asset_tag FROM slots WHERE id = 811;").fetchone()
        occupancy = conn.execute(
            """
            SELECT slot_id
            FROM slot_occupancy
            WHERE asset_id = ?
            ORDER BY slot_id ASC;
            """,
            (int(asset["id"]),),
        ).fetchall()
        events = conn.execute(
            """
            SELECT event_type, payload, holder_id
            FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id ASC;
            """,
            (asset_tag,),
        ).fetchall()
        receipts = conn.execute("SELECT COUNT(*) AS c FROM receipt_queue;").fetchone()
    finally:
        conn.close()

    return {
        "asset": dict(asset),
        "source_slot": dict(source_slot),
        "destination_slot": dict(destination_slot),
        "occupancy_slots": [int(row["slot_id"]) for row in occupancy],
        "events": [dict(row) for row in events],
        "receipt_count": int(receipts["c"]),
    }


def _slot_move_expected_fields(asset_tag: str = "MOVE-100", destination_slot_id: int = 811) -> dict[str, str]:
    conn = db.get_connection()
    try:
        asset = conn.execute("SELECT id FROM assets WHERE asset_tag = ? LIMIT 1;", (asset_tag,)).fetchone()
    finally:
        conn.close()
    return {
        "expected_asset_id": str(int(asset["id"])),
        "expected_destination_slot_id": str(destination_slot_id),
    }


def _slot_move_commit_data(
    source_slot_id: int = 810,
    case_number: str = "CASE-DST",
    slot_number: str = "2",
    *,
    expected_asset_tag: str = "MOVE-100",
    destination_slot_id: int = 811,
    include_expected: bool = True,
) -> dict[str, str]:
    data = {
        "action": "commit",
        "source_slot_id": str(source_slot_id),
        "destination_slot_id": str(destination_slot_id),
        "building_room": "DST/202",
        "case_number": case_number,
        "slot_number": slot_number,
        "notes": "rack move",
    }
    if include_expected:
        data.update(_slot_move_expected_fields(expected_asset_tag, destination_slot_id))
    return data


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
    _create_building("HQ")

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

    slot_conn = db.get_connection()
    try:
        target_slot = slot_conn.execute(
            "SELECT id FROM slots WHERE case_name = 'CASE-Q' AND slot_position = 1 LIMIT 1;"
        ).fetchone()
    finally:
        slot_conn.close()
    assert target_slot is not None

    assigned = client_with_temp_db.post(
        "/admin/assign-slot",
        data={
            "action": "assign",
            "asset_tag": "AT-UNSLOT-1",
            "building": "HQ",
            "room": "100",
            "case_name": "CASE-Q",
            "slot_id": str(int(target_slot["id"])),
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
    _create_building("HQ")
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
    _create_building("HQ")
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
    _create_building("HQ")
    created = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-SELECT-1",
            "serial_number": "SER-SELECT-1",
            "manufacturer": "Dell",
            "equipment_type": "laptop",
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
    assert b'name="case_name"' in response.data
    assert b'name="slot_id"' in response.data


def test_assign_slot_manual_lookup_still_works(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
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


def test_assign_slot_selectors_hide_occupied_slot_options(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (501, 'CASE-SEL', 1, 'AT-BUSY'), (502, 'CASE-SEL', 2, NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-SELECTOR-1",
            "serial_number": "SER-SELECTOR-1",
            "manufacturer": "Dell",
            "equipment_type": "laptop",
            "building": "HQ",
            "room": "100",
        },
    )
    assert response.status_code == 302

    lookup = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "lookup", "asset_tag": "AT-SELECTOR-1"},
        follow_redirects=True,
    )
    assert lookup.status_code == 200
    assert b"CASE-SEL / Slot 1 - occupied" in lookup.data
    assert b"CASE-SEL / Slot 2" in lookup.data
    assert b"disabled" in lookup.data


def test_assign_slot_page_shows_known_buildings_as_choices(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ North")
    _create_building("HQ South")
    created = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-BUILDING-CHOICE",
            "serial_number": "SER-BUILDING-CHOICE",
            "manufacturer": "Dell",
            "equipment_type": "laptop",
            "building": "HQ North",
            "room": "100",
        },
    )
    assert created.status_code == 302

    response = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "lookup", "asset_tag": "AT-BUILDING-CHOICE"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'<option value="HQ North"' in response.data
    assert b'<option value="HQ South"' in response.data


def test_assign_slot_page_hides_inactive_buildings_from_choices(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ North")
    _create_building("Closed HQ")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE buildings SET is_active = 0 WHERE name = 'Closed HQ';")
        conn.commit()
    finally:
        conn.close()

    created = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-ACTIVE-BUILDING-CHOICE",
            "serial_number": "SER-ACTIVE-BUILDING-CHOICE",
            "manufacturer": "Dell",
            "equipment_type": "laptop",
            "building": "HQ North",
            "room": "100",
        },
    )
    assert created.status_code == 302

    response = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "lookup", "asset_tag": "AT-ACTIVE-BUILDING-CHOICE"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'<option value="HQ North"' in response.data
    assert b'<option value="Closed HQ"' not in response.data


def test_assign_slot_rejects_stale_inactive_building_without_appending_slot_assign(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    _create_building("Closed HQ")
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (701, 'CASE-INACTIVE-BLD', 1, NULL);
            """
        )
        conn.execute("UPDATE buildings SET is_active = 0 WHERE name = 'Closed HQ';")
        conn.commit()
    finally:
        conn.close()

    created = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-INACTIVE-BLD",
            "serial_number": "SER-INACTIVE-BLD",
            "manufacturer": "Dell",
            "equipment_type": "laptop",
            "building": "HQ",
            "room": "100",
        },
    )
    assert created.status_code == 302

    assign_attempt = client_with_temp_db.post(
        "/admin/assign-slot",
        data={
            "action": "assign",
            "asset_tag": "AT-INACTIVE-BLD",
            "building": "Closed HQ",
            "room": "100",
            "case_name": "CASE-INACTIVE-BLD",
            "slot_id": "701",
        },
        follow_redirects=True,
    )

    assert assign_attempt.status_code == 200
    assert b"Choose a valid building." in assign_attempt.data

    verify_conn = db.get_connection()
    try:
        asset_row = verify_conn.execute(
            "SELECT id, home_slot_id FROM assets WHERE asset_tag = 'AT-INACTIVE-BLD' LIMIT 1;"
        ).fetchone()
        occupancy = verify_conn.execute(
            "SELECT 1 FROM slot_occupancy WHERE asset_id = ? LIMIT 1;",
            (int(asset_row["id"]),),
        ).fetchone()
        slot_row = verify_conn.execute(
            "SELECT current_asset_tag FROM slots WHERE id = 701;"
        ).fetchone()
        events = verify_conn.execute(
            "SELECT event_type FROM asset_events WHERE asset_tag = 'AT-INACTIVE-BLD' ORDER BY id ASC;"
        ).fetchall()
    finally:
        verify_conn.close()

    assert asset_row["home_slot_id"] is None
    assert occupancy is None
    assert slot_row["current_asset_tag"] is None
    assert [str(row["event_type"]) for row in events] == ["ASSET_CREATED"]


def test_assign_slot_rejects_arbitrary_building_without_appending_slot_assign(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (700, 'CASE-BLD', 1, NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()

    created = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-BAD-BLD",
            "serial_number": "SER-BAD-BLD",
            "manufacturer": "Dell",
            "equipment_type": "laptop",
            "building": "HQ",
            "room": "100",
        },
    )
    assert created.status_code == 302

    assign_attempt = client_with_temp_db.post(
        "/admin/assign-slot",
        data={
            "action": "assign",
            "asset_tag": "AT-BAD-BLD",
            "building": "booger",
            "room": "100",
            "case_name": "CASE-BLD",
            "slot_id": "700",
        },
        follow_redirects=True,
    )
    assert assign_attempt.status_code == 200
    assert b"Choose a valid building." in assign_attempt.data

    verify_conn = db.get_connection()
    try:
        asset_row = verify_conn.execute(
            "SELECT id, home_slot_id FROM assets WHERE asset_tag = 'AT-BAD-BLD' LIMIT 1;"
        ).fetchone()
        occupancy = verify_conn.execute(
            "SELECT 1 FROM slot_occupancy WHERE asset_id = ? LIMIT 1;",
            (int(asset_row["id"]),),
        ).fetchone()
        events = verify_conn.execute(
            "SELECT event_type FROM asset_events WHERE asset_tag = 'AT-BAD-BLD' ORDER BY id ASC;"
        ).fetchall()
    finally:
        verify_conn.close()

    assert asset_row["home_slot_id"] is None
    assert occupancy is None
    assert [str(row["event_type"]) for row in events] == ["ASSET_CREATED"]


def test_operator_denied_slot_move_preview_and_commit(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-slot-move", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)
    _insert_slot_move_fixture()

    entry_response = client_with_temp_db.get("/admin/slot-move")
    preview_response = client_with_temp_db.post(
        "/admin/slot-move",
        data={
            "action": "preview",
            "source_slot_id": "810",
            "building_room": "DST/202",
            "case_number": "CASE-DST",
            "slot_number": "2",
        },
    )
    commit_response = client_with_temp_db.post(
        "/admin/slot-move",
        data={
            "action": "commit",
            "source_slot_id": "810",
            "building_room": "DST/202",
            "case_number": "CASE-DST",
            "slot_number": "2",
        },
    )

    assert entry_response.status_code == 403
    assert preview_response.status_code == 403
    assert commit_response.status_code == 403
    assert _slot_move_state()["occupancy_slots"] == [810]


def test_slot_move_entry_lists_occupied_sources_without_slot_id(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture()

    response = client_with_temp_db.get("/admin/slot-move")

    assert response.status_code == 200
    assert b"Select Source Slot" in response.data
    assert b"MOVE-100" in response.data
    assert b"SER-MOVE-100" in response.data
    assert b"switch" in response.data
    assert b"CASE-SRC" in response.data
    assert b"SRC/101" in response.data
    assert b"Select" in response.data
    assert b"slot_id is required" not in response.data
    assert b"Provide a valid" not in response.data
    assert b"/admin/slot-move?slot_id=" not in response.data


def test_slot_move_entry_does_not_offer_empty_slots_as_sources(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture()

    response = client_with_temp_db.get("/admin/slot-move")

    assert response.status_code == 200
    assert b"CASE-SRC" in response.data
    assert b"CASE-DST" not in response.data


def test_slot_move_selecting_source_continues_to_destination_selection(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture()

    response = client_with_temp_db.get("/admin/slot-move?slot_id=810")

    assert response.status_code == 200
    assert b"Source Slot Details" in response.data
    assert b"Move To Destination Slot" in response.data
    assert b"Occupied Source Slots" in response.data
    assert b"Empty Destination Slots" in response.data
    assert b"Only empty slots are shown." in response.data
    assert b'name="source_slot_id" value="810"' in response.data
    assert b'name="destination_slot_id" value="811"' in response.data
    source_details_index = response.data.index(b"Source Slot Details")
    source_list_index = response.data.index(b"Occupied Source Slots")
    destination_list_index = response.data.index(b"Empty Destination Slots")
    destination_slot_index = response.data.index(b'name="destination_slot_id" value="811"')
    assert source_details_index < source_list_index
    assert destination_list_index < destination_slot_index


def test_slot_move_destination_list_shows_empty_slots_and_excludes_source(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture()

    response = client_with_temp_db.get("/admin/slot-move?slot_id=810")

    assert response.status_code == 200
    assert b"SRC/101" in response.data
    assert b"<code>CASE-DST</code>" in response.data
    assert b"<code>2</code>" in response.data
    assert b'name="destination_slot_id" value="811"' in response.data
    assert b'name="destination_slot_id" value="810"' not in response.data
    assert b'id="building_room"' not in response.data
    assert b'id="case_number"' not in response.data
    assert b'id="slot_number"' not in response.data


def test_slot_move_destination_list_hides_occupied_slots(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture(destination_occupied=True)

    response = client_with_temp_db.get("/admin/slot-move?slot_id=810")

    assert response.status_code == 200
    assert b'name="destination_slot_id" value="811"' not in response.data
    assert b"No empty destination slots found." in response.data


def test_slot_move_selecting_destination_reaches_preview(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture()
    before = _slot_move_state()

    response = client_with_temp_db.post(
        "/admin/slot-move",
        data={
            "action": "preview",
            "source_slot_id": "810",
            "destination_slot_id": "811",
            "building_room": "SRC/101",
        },
    )
    after = _slot_move_state()

    assert response.status_code == 200
    assert b"Preview Move" in response.data
    assert b"Confirm Move" in response.data
    assert b"MOVE-100" in response.data
    assert b"CASE-SRC" in response.data
    assert b"CASE-DST" in response.data
    assert b"Empty Destination Slots" in response.data
    assert b'name="destination_slot_id" value="811"' in response.data
    assert b'name="expected_destination_slot_id" value="811"' in response.data
    preview_index = response.data.index(b"Preview Move")
    confirm_index = response.data.index(b"Confirm Move")
    destination_list_index = response.data.index(b"Empty Destination Slots")
    destination_select_index = response.data.rindex(b'name="destination_slot_id" value="811"')
    assert preview_index < destination_list_index
    assert confirm_index < destination_list_index
    assert destination_list_index < destination_select_index
    assert after == before


def test_slot_move_valid_slot_id_deep_link_still_works(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture(source_slot_id=820, destination_slot_id=821)

    response = client_with_temp_db.get("/admin/slot-move?slot_id=820")

    assert response.status_code == 200
    assert b"MOVE-100" in response.data
    assert b"CASE-SRC" in response.data
    assert b"Move To Destination Slot" in response.data


def test_slot_move_preview_displays_facts_without_changing_state(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture(current_holder_id=44)
    before = _slot_move_state()

    response = client_with_temp_db.post(
        "/admin/slot-move",
        data={
            "action": "preview",
            "source_slot_id": "810",
            "destination_slot_id": "811",
            "notes": "rack move",
        },
    )
    after = _slot_move_state()

    assert response.status_code == 200
    assert b"Preview Move" in response.data
    assert b"MOVE-100" in response.data
    assert b"SER-MOVE-100" in response.data
    assert b"switch" in response.data
    assert b"CASE-SRC" in response.data
    assert b"CASE-DST" in response.data
    assert b"SRC" in response.data
    assert b"101" in response.data
    assert b"DST" in response.data
    assert b"101" in response.data
    assert b"Custody will not change." in response.data
    assert b"No custody receipt will be generated." in response.data
    assert b"Confirm Move" in response.data
    assert after == before


@pytest.mark.parametrize(
    ("equipment_type", "holder_id"),
    [
        ("laptop", 44),
        ("switch", None),
        ("router", None),
    ],
)
def test_slot_move_confirm_moves_supported_stored_asset_types_without_custody_or_receipt_change(
    client_with_temp_db,
    equipment_type: str,
    holder_id: int | None,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture(equipment_type=equipment_type, current_holder_id=holder_id)

    response = client_with_temp_db.post(
        "/admin/slot-move",
        data=_slot_move_commit_data(),
        follow_redirects=True,
    )
    state = _slot_move_state()

    assert response.status_code == 200
    assert state["source_slot"]["current_asset_tag"] is None
    assert state["destination_slot"]["current_asset_tag"] == "MOVE-100"
    assert state["occupancy_slots"] == [811]
    assert state["receipt_count"] == 0
    assert state["asset"]["location_type"] == "STORAGE"
    assert state["asset"]["current_holder_id"] == holder_id
    assert int(state["asset"]["home_slot_id"]) == 811
    assert state["asset"]["building"] == "SRC"
    assert state["asset"]["room"] == "101"
    assert state["asset"]["building_room"] == "SRC/101"
    assert state["asset"]["case_number"] == "CASE-DST"
    assert str(state["asset"]["slot_number"]) == "2"
    assert [event["event_type"] for event in state["events"]] == ["SLOT_MOVE"]
    assert state["events"][0]["holder_id"] is None


def test_slot_move_confirm_moves_storage_asset_without_custody_or_receipt_change(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture(current_holder_id=44)

    response = client_with_temp_db.post(
        "/admin/slot-move",
        data=_slot_move_commit_data(),
        follow_redirects=True,
    )
    state = _slot_move_state()

    assert response.status_code == 200
    assert b"Moved asset MOVE-100 from case CASE-SRC, slot 1 to case CASE-DST, slot 2." in response.data
    assert state["source_slot"]["current_asset_tag"] is None
    assert state["destination_slot"]["current_asset_tag"] == "MOVE-100"
    assert state["occupancy_slots"] == [811]
    assert state["receipt_count"] == 0

    asset = state["asset"]
    assert asset["location_type"] == "STORAGE"
    assert int(asset["current_holder_id"]) == 44
    assert int(asset["home_slot_id"]) == 811
    assert asset["building"] == "SRC"
    assert asset["room"] == "101"
    assert asset["building_room"] == "SRC/101"
    assert asset["case_number"] == "CASE-DST"
    assert str(asset["slot_number"]) == "2"

    events = state["events"]
    assert [event["event_type"] for event in events] == ["SLOT_MOVE"]
    assert events[0]["holder_id"] is None
    payload = json.loads(str(events[0]["payload"]))
    assert payload["from_slot"] == {
        "slot_id": 810,
        "building_room": "SRC/101",
        "case_number": "CASE-SRC",
        "slot_number": 1,
    }
    assert payload["to_slot"] == {
        "slot_id": 811,
        "building_room": "SRC/101",
        "case_number": "CASE-DST",
        "slot_number": 2,
    }


def test_slot_move_repeated_confirmation_does_not_append_second_slot_move(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture()
    stale_commit_data = _slot_move_commit_data()

    first = client_with_temp_db.post("/admin/slot-move", data=stale_commit_data, follow_redirects=True)
    second = client_with_temp_db.post("/admin/slot-move", data=stale_commit_data, follow_redirects=True)
    state = _slot_move_state()

    assert first.status_code == 200
    assert second.status_code == 200
    assert b"Source slot is missing or empty." in second.data
    assert state["source_slot"]["current_asset_tag"] is None
    assert state["destination_slot"]["current_asset_tag"] == "MOVE-100"
    assert state["occupancy_slots"] == [811]
    assert [event["event_type"] for event in state["events"]] == ["SLOT_MOVE"]
    assert state["receipt_count"] == 0


def test_slot_move_rejects_stale_source_reoccupied_by_different_asset_without_partial_change(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture()
    stale_commit_data = _slot_move_commit_data()
    conn = db.get_connection()
    try:
        move_asset = conn.execute("SELECT id FROM assets WHERE asset_tag = 'MOVE-100';").fetchone()
        conn.execute("DELETE FROM slot_occupancy WHERE slot_id = 810;")
        other_cursor = conn.execute(
            """
            INSERT INTO assets (
                asset_tag,
                serial_number,
                equipment_type,
                manufacturer,
                building,
                room,
                building_room,
                custody_state,
                accountability_status,
                condition,
                created_date,
                updated_date,
                location_type,
                current_holder_id,
                home_slot_id,
                case_number,
                slot_number
            )
            VALUES ('OTHER-SOURCE', 'SER-OTHER-SOURCE', 'router', 'Cisco', 'SRC', '101', 'SRC/101',
                    'in_stock', 'accountable', 'serviceable', '2026-01-01', '2026-01-01T00:00:00Z',
                    'STORAGE', NULL, 810, 'CASE-SRC', '1');
            """
        )
        conn.execute(
            "INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at) VALUES (810, ?, '2026-01-02T00:00:00Z');",
            (int(other_cursor.lastrowid),),
        )
        conn.execute("UPDATE slots SET current_asset_tag = 'OTHER-SOURCE' WHERE id = 810;")
        conn.commit()
        before_move = conn.execute(
            "SELECT location_type, current_holder_id, home_slot_id, building_room, case_number, slot_number FROM assets WHERE id = ?;",
            (int(move_asset["id"]),),
        ).fetchone()
    finally:
        conn.close()

    response = client_with_temp_db.post("/admin/slot-move", data=stale_commit_data, follow_redirects=True)

    conn = db.get_connection()
    try:
        after_move = conn.execute(
            "SELECT location_type, current_holder_id, home_slot_id, building_room, case_number, slot_number FROM assets WHERE asset_tag = 'MOVE-100';"
        ).fetchone()
        other_occupancy = conn.execute(
            """
            SELECT so.slot_id
            FROM slot_occupancy so
            JOIN assets a ON a.id = so.asset_id
            WHERE a.asset_tag = 'OTHER-SOURCE';
            """
        ).fetchone()
        destination = conn.execute("SELECT current_asset_tag FROM slots WHERE id = 811;").fetchone()
        events = conn.execute("SELECT event_type FROM asset_events ORDER BY id ASC;").fetchall()
        receipts = conn.execute("SELECT COUNT(*) AS c FROM receipt_queue;").fetchone()
    finally:
        conn.close()

    assert response.status_code == 200
    assert b"Source slot changed. Preview the move again." in response.data
    assert dict(after_move) == dict(before_move)
    assert int(other_occupancy["slot_id"]) == 810
    assert destination["current_asset_tag"] is None
    assert events == []
    assert int(receipts["c"]) == 0


def test_slot_move_commit_rejects_stale_empty_source_without_partial_change(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture()
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM slot_occupancy WHERE slot_id = 810;")
        conn.execute("UPDATE slots SET current_asset_tag = NULL WHERE id = 810;")
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.post(
        "/admin/slot-move",
        data={
            "action": "commit",
            "source_slot_id": "810",
            "destination_slot_id": "811",
        },
        follow_redirects=True,
    )
    state = _slot_move_state()

    assert response.status_code == 200
    assert b"Source slot is missing or empty." in response.data
    assert state["source_slot"]["current_asset_tag"] is None
    assert state["destination_slot"]["current_asset_tag"] is None
    assert state["occupancy_slots"] == []
    assert state["events"] == []
    assert state["receipt_count"] == 0


def test_slot_move_commit_rejects_marker_only_occupied_destination_without_partial_change(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture()
    conn = db.get_connection()
    try:
        conn.execute("UPDATE slots SET current_asset_tag = 'MARKER-ONLY' WHERE id = 811;")
        conn.commit()
    finally:
        conn.close()
    before = _slot_move_state()

    response = client_with_temp_db.post(
        "/admin/slot-move",
        data=_slot_move_commit_data(),
        follow_redirects=True,
    )
    after = _slot_move_state()

    assert response.status_code == 200
    assert b"Destination slot is already occupied." in response.data
    assert after == before


def test_slot_move_commit_rejects_stale_occupied_destination_without_partial_change(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture(destination_occupied=True)

    response = client_with_temp_db.post(
        "/admin/slot-move",
        data={
            "action": "commit",
            "source_slot_id": "810",
            "destination_slot_id": "811",
        },
        follow_redirects=True,
    )
    state = _slot_move_state()

    assert response.status_code == 200
    assert b"Destination slot is already occupied." in response.data
    assert state["source_slot"]["current_asset_tag"] == "MOVE-100"
    assert state["destination_slot"]["current_asset_tag"] == "OTHER-DEST"
    assert state["occupancy_slots"] == [810]
    assert state["events"] == []
    assert state["receipt_count"] == 0


def test_slot_move_commit_rejects_identical_source_and_destination_without_partial_change(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture()
    before = _slot_move_state()

    response = client_with_temp_db.post(
        "/admin/slot-move",
        data=_slot_move_commit_data(case_number="CASE-SRC", slot_number="1", destination_slot_id=810),
        follow_redirects=True,
    )
    after = _slot_move_state()

    assert response.status_code == 200
    assert b"Moving to the same slot is not allowed." in response.data
    assert after == before


def test_slot_move_commit_rejects_in_custody_asset_without_partial_change(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture(location_type="IN_CUSTODY", current_holder_id=44)
    before = _slot_move_state()

    response = client_with_temp_db.post(
        "/admin/slot-move",
        data=_slot_move_commit_data(),
        follow_redirects=True,
    )
    after = _slot_move_state()

    assert response.status_code == 200
    assert b"Asset must be location_type=STORAGE." in response.data
    assert after == before


@pytest.mark.parametrize(
    ("location_type", "failure_type"),
    [
        ("RETIRED", "HARDWARE"),
        ("DISPOSED", "HARDWARE"),
        ("DISPOSED", "LOST"),
        ("DISPOSED", "OTHER"),
    ],
)
def test_slot_move_commit_rejects_terminal_assets_without_partial_change(
    client_with_temp_db,
    location_type: str,
    failure_type: str,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot_move_fixture(location_type=location_type)
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
            VALUES ('MOVE-100', 'ASSET_RETIRED', '2026-01-01T01:00:00Z', 'admin', NULL, ?, NULL);
            """,
            (json.dumps({"failure_type": failure_type, "to_location_type": location_type}),),
        )
        conn.commit()
    finally:
        conn.close()
    before = _slot_move_state()

    response = client_with_temp_db.post(
        "/admin/slot-move",
        data=_slot_move_commit_data(),
        follow_redirects=True,
    )
    after = _slot_move_state()

    assert response.status_code == 200
    assert b"Asset is retired/disposed and cannot be moved." in response.data
    assert after == before
