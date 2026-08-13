from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

import assettrack.db as db
from assettrack.cases import CASE_SIZE_OPTIONS
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


LAPTOP_CASE_SIZE_OPTIONS = (
    "10 Slot Laptop Case",
    "18 Slot Laptop Case",
    "30 Slot Laptop Case",
)


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


def _create_unslotted_asset(
    client_with_temp_db,
    *,
    asset_tag: str,
    serial_number: str,
    equipment_type: str = "laptop",
) -> None:
    response = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": asset_tag,
            "serial_number": serial_number,
            "manufacturer": "Dell",
            "equipment_type": equipment_type,
            "building": "HQ",
            "room": "100",
        },
    )
    assert response.status_code == 302


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


def _insert_case_correction_fixture(*, case_name: str = "CASE-OLD", used: bool = True, with_event: bool = True) -> int:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES
                (1901, ?, 1, ?),
                (1902, ?, 2, NULL);
            """,
            (case_name, "CASE-ASSET-1" if used else None, case_name),
        )
        asset_id = 0
        if used:
            cursor = conn.execute(
                """
                INSERT INTO assets (
                    asset_tag,
                    location_type,
                    home_slot_id,
                    case_number,
                    slot_number,
                    building_room
                )
                VALUES ('CASE-ASSET-1', 'STORAGE', 1901, ?, '1', 'HQ/101');
                """,
                (case_name,),
            )
            asset_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
                VALUES (1901, ?, '2026-01-01T00:00:00+00:00');
                """,
                (asset_id,),
            )
            if with_event:
                conn.execute(
                    """
                    INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
                    VALUES ('CASE-ASSET-1', 'SLOT_ASSIGN', '2026-01-01T00:00:00+00:00', 'admin', NULL, ?, NULL);
                    """,
                    (json.dumps({"slot": {"case_number": case_name, "slot_number": 1}}),),
                )
        conn.commit()
        return asset_id
    finally:
        conn.close()


def _case_correction_state() -> dict[str, object]:
    conn = db.get_connection()
    try:
        slots = conn.execute(
            """
            SELECT id, case_name, slot_position, current_asset_tag
            FROM slots
            ORDER BY id ASC;
            """
        ).fetchall()
        assets = conn.execute(
            """
            SELECT asset_tag, home_slot_id, case_number, slot_number
            FROM assets
            ORDER BY asset_tag ASC;
            """
        ).fetchall()
        occupancy = conn.execute(
            """
            SELECT slot_id, asset_id
            FROM slot_occupancy
            ORDER BY slot_id ASC;
            """
        ).fetchall()
        events = conn.execute(
            """
            SELECT event_type, payload
            FROM asset_events
            ORDER BY id ASC;
            """
        ).fetchall()
        corrections = conn.execute(
            """
            SELECT event_type, actor_user_id, actor_username, old_case_name, new_case_name, affected_slot_count, affected_asset_count
            FROM case_correction_events
            ORDER BY id ASC;
            """
        ).fetchall()
        return {
            "slots": [dict(row) for row in slots],
            "assets": [dict(row) for row in assets],
            "occupancy": [dict(row) for row in occupancy],
            "events": [dict(row) for row in events],
            "corrections": [dict(row) for row in corrections],
        }
    finally:
        conn.close()


def test_admin_slot_provision_creates_new_empty_slots_for_case(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (3901, 'CASE-P', 1, NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()

    preview_response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={"action": "preview", "case_number": "CASE-P", "slot_identifiers": "2 3 4"},
    )
    assert preview_response.status_code == 200
    assert b"Admin: Provision Case / Slots" in preview_response.data
    assert b"Provision case / slots" in preview_response.data
    assert b"Slot provisioning preview ready. Review before committing." in preview_response.data
    assert b"Preview empty slots" in preview_response.data
    assert b"Empty Slot" in preview_response.data

    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM slots WHERE case_name = 'CASE-P';").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM slot_occupancy;").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM case_metadata;").fetchone()[0] == 0
    finally:
        conn.close()

    commit_response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={
            "action": "commit",
            "case_number": "CASE-P",
            "slot_identifiers": "2 3 4",
            "expected_case_number": "CASE-P",
            "expected_slot_identifiers": "2 3 4",
            "confirm_slot_provision": "yes",
        },
        follow_redirects=True,
    )
    assert commit_response.status_code == 200
    assert b"Created 3 empty slots for case CASE-P: 2, 3, 4." in commit_response.data

    verify_conn = db.get_connection()
    try:
        rows = verify_conn.execute(
            """
            SELECT case_name, slot_position, current_asset_tag
            FROM slots
            WHERE case_name = 'CASE-P'
            ORDER BY slot_position ASC;
            """
        ).fetchall()
    finally:
        verify_conn.close()

    assert [(row["case_name"], row["slot_position"], row["current_asset_tag"]) for row in rows] == [
        ("CASE-P", 1, None),
        ("CASE-P", 2, None),
        ("CASE-P", 3, None),
        ("CASE-P", 4, None),
    ]


def test_admin_slot_provision_creates_new_case_slots_from_slot_count(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    preview_response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={
            "action": "preview",
            "provision_mode": "new",
            "new_case_number": "case-new-provision",
            "slot_count": "3",
        },
    )
    assert preview_response.status_code == 200
    assert b"Slot provisioning preview ready. Review before committing." in preview_response.data
    assert b'name="provision_mode" value="new"' in preview_response.data
    assert b'name="slot_count" value="3"' in preview_response.data
    assert b'name="expected_slot_count" value="3"' in preview_response.data
    assert b"<code>CASE-NEW-PROVISION</code>" in preview_response.data
    assert b"<code>1</code>" in preview_response.data
    assert b"<code>2</code>" in preview_response.data
    assert b"<code>3</code>" in preview_response.data
    assert preview_response.data.count(b"Empty Slot") == 3

    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM slots;").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM slot_occupancy;").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM case_metadata;").fetchone()[0] == 0
    finally:
        conn.close()

    commit_response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={
            "action": "commit",
            "provision_mode": "new",
            "case_number": "CASE-NEW-PROVISION",
            "new_case_number": "CASE-NEW-PROVISION",
            "slot_count": "3",
            "expected_provision_mode": "new",
            "expected_case_number": "CASE-NEW-PROVISION",
            "expected_slot_count": "3",
            "confirm_slot_provision": "yes",
        },
        follow_redirects=True,
    )
    assert commit_response.status_code == 200
    assert b"Created 3 empty slots for case CASE-NEW-PROVISION: 1, 2, 3." in commit_response.data

    verify_conn = db.get_connection()
    try:
        rows = verify_conn.execute(
            """
            SELECT case_name, slot_position, current_asset_tag
            FROM slots
            WHERE case_name = 'CASE-NEW-PROVISION'
            ORDER BY slot_position ASC;
            """
        ).fetchall()
    finally:
        verify_conn.close()

    assert [(row["case_name"], row["slot_position"], row["current_asset_tag"]) for row in rows] == [
        ("CASE-NEW-PROVISION", 1, None),
        ("CASE-NEW-PROVISION", 2, None),
        ("CASE-NEW-PROVISION", 3, None),
    ]

    detail_response = client_with_temp_db.get("/dashboard/cases/CASE-NEW-PROVISION")
    assert detail_response.status_code == 200
    assert b"CASE-NEW-PROVISION" in detail_response.data
    assert b"Total slots:</strong> 3" in detail_response.data


@pytest.mark.parametrize(
    ("slot_count", "message"),
    [
        ("", "slot_count is required."),
        ("0", "slot_count must be greater than 0."),
        ("-1", "slot_count must be greater than 0."),
        ("abc", "slot_count must be an integer."),
    ],
)
def test_admin_slot_provision_new_case_rejects_invalid_slot_count(
    client_with_temp_db,
    slot_count: str,
    message: str,
) -> None:
    _login_admin(client_with_temp_db)

    response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={
            "action": "preview",
            "provision_mode": "new",
            "new_case_number": "case-bad-count",
            "slot_count": slot_count,
        },
    )

    assert response.status_code == 200
    assert message.encode() in response.data
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM slots;").fetchone()[0] == 0
    finally:
        conn.close()


def test_admin_slot_provision_new_case_blocks_commit_when_slot_count_changes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={
            "action": "commit",
            "provision_mode": "new",
            "case_number": "CASE-COUNT-TAMPER",
            "new_case_number": "CASE-COUNT-TAMPER",
            "slot_count": "4",
            "expected_provision_mode": "new",
            "expected_case_number": "CASE-COUNT-TAMPER",
            "expected_slot_count": "3",
            "confirm_slot_provision": "yes",
        },
    )

    assert response.status_code == 200
    assert b"Preview changed. Review the slot provisioning preview again before committing." in response.data
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM slots WHERE case_name = 'CASE-COUNT-TAMPER';").fetchone()[0] == 0
    finally:
        conn.close()


def test_admin_slot_provision_new_case_mode_rejects_existing_case(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (3911, 'CASE-EXISTS', 1, NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={
            "action": "preview",
            "provision_mode": "new",
            "new_case_number": "case-exists",
            "slot_count": "2",
        },
    )

    assert response.status_code == 200
    assert b"Case CASE-EXISTS already exists. Select existing-case mode to add slots." in response.data
    verify_conn = db.get_connection()
    try:
        rows = verify_conn.execute(
            "SELECT slot_position FROM slots WHERE case_name = 'CASE-EXISTS' ORDER BY slot_position ASC;"
        ).fetchall()
    finally:
        verify_conn.close()
    assert [int(row["slot_position"]) for row in rows] == [1]


def test_existing_case_may_remain_blank_case_size(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (30, 'CASE-BLANK-SIZE', 1, NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.get("/dashboard/cases/CASE-BLANK-SIZE")

    assert response.status_code == 200
    assert b"Case Size:</strong> Not recorded" in response.data


def test_admin_case_size_update_accepts_every_menu_choice(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (31, 'CASE-EDIT-SIZE', 1, NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()

    for option in CASE_SIZE_OPTIONS:
        response = client_with_temp_db.post(
            "/admin/cases/CASE-EDIT-SIZE/case-size",
            data={"case_size": option},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert option.encode() in response.data

    verify_conn = db.get_connection()
    try:
        metadata = verify_conn.execute(
            "SELECT case_size FROM case_metadata WHERE case_name = 'CASE-EDIT-SIZE';"
        ).fetchone()
        slot_count = verify_conn.execute("SELECT COUNT(*) FROM slots WHERE case_name = 'CASE-EDIT-SIZE';").fetchone()[0]
    finally:
        verify_conn.close()

    assert metadata["case_size"] == CASE_SIZE_OPTIONS[-1]
    assert slot_count == 1



def test_admin_case_size_update_saves_laptop_choices_without_changing_slots_or_events(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES
                (3301, 'CASE-LAPTOP-SIZE', 1, NULL),
                (3302, 'CASE-LAPTOP-SIZE', 2, NULL);
            """
        )
        conn.execute(
            """
            INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload)
            VALUES ('LAPTOP-SIZE-AUDIT', 'created', '2026-01-01T00:00:00Z', 'system', NULL, '{}');
            """
        )
        conn.commit()
    finally:
        conn.close()

    detail_response = client_with_temp_db.get("/dashboard/cases/CASE-LAPTOP-SIZE")
    assert detail_response.status_code == 200
    for option in LAPTOP_CASE_SIZE_OPTIONS:
        assert f'<option value="{option}"'.encode() in detail_response.data

    for option in LAPTOP_CASE_SIZE_OPTIONS:
        response = client_with_temp_db.post(
            "/admin/cases/CASE-LAPTOP-SIZE/case-size",
            data={"case_size": option},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert option.encode() in response.data
        assert b"Total slots:</strong> 2" in response.data
        assert b"Available slots:</strong> 2" in response.data

        verify_conn = db.get_connection()
        try:
            metadata = verify_conn.execute(
                "SELECT case_size FROM case_metadata WHERE case_name = 'CASE-LAPTOP-SIZE';"
            ).fetchone()
            slot_rows = verify_conn.execute(
                "SELECT id, slot_position, current_asset_tag FROM slots WHERE case_name = 'CASE-LAPTOP-SIZE' ORDER BY id ASC;"
            ).fetchall()
            event_rows = verify_conn.execute(
                "SELECT asset_tag, event_type, payload FROM asset_events ORDER BY id ASC;"
            ).fetchall()
        finally:
            verify_conn.close()

        assert metadata["case_size"] == option
        assert [(row["id"], row["slot_position"], row["current_asset_tag"]) for row in slot_rows] == [
            (3301, 1, None),
            (3302, 2, None),
        ]
        assert [(row["asset_tag"], row["event_type"], row["payload"]) for row in event_rows] == [
            ("LAPTOP-SIZE-AUDIT", "created", "{}"),
        ]

def test_operator_cannot_edit_case_size(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-case-size", password="operator-pass", role="operator")
    login_session(client_with_temp_db, operator_id)
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (32, 'CASE-ROLE-SIZE', 1, NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.post(
        "/admin/cases/CASE-ROLE-SIZE/case-size",
        data={"case_size": "Small Wheel"},
    )

    assert response.status_code == 403


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

    preview_response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={"action": "preview", "case_number": "CASE-P", "slot_identifiers": "3, 4"},
    )
    assert preview_response.status_code == 200
    assert b"Slot provisioning preview ready. Review before committing." in preview_response.data

    response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={
            "action": "commit",
            "case_number": "CASE-P",
            "slot_identifiers": "3, 4",
            "expected_case_number": "CASE-P",
            "expected_slot_identifiers": "3, 4",
            "confirm_slot_provision": "yes",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Created 2 empty slots for case CASE-P: 3, 4." in response.data

    verify_conn = db.get_connection()
    try:
        rows = verify_conn.execute(
            "SELECT slot_position FROM slots WHERE case_name = 'CASE-P' ORDER BY slot_position ASC;"
        ).fetchall()
    finally:
        verify_conn.close()
    assert [int(row["slot_position"]) for row in rows] == [1, 2, 3, 4]


def test_admin_slot_provision_blocks_duplicate_identifiers_in_request(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO slots (case_name, slot_position, current_asset_tag) VALUES ('CASE-DUP', 1, NULL);")
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={"action": "preview", "case_number": "CASE-DUP", "slot_identifiers": "2 2"},
    )

    assert response.status_code == 200
    assert b"Duplicate slot identifiers in request: 2." in response.data
    verify_conn = db.get_connection()
    try:
        assert verify_conn.execute("SELECT COUNT(*) FROM slots WHERE case_name = 'CASE-DUP';").fetchone()[0] == 1
    finally:
        verify_conn.close()


def test_admin_slot_provision_blocks_existing_slots_and_repeat_submission(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO slots (case_name, slot_position, current_asset_tag) VALUES ('CASE-REPEAT', 1, NULL);")
        conn.commit()
    finally:
        conn.close()

    data = {
        "action": "commit",
        "case_number": "CASE-REPEAT",
        "slot_identifiers": "2 3",
        "expected_case_number": "CASE-REPEAT",
        "expected_slot_identifiers": "2 3",
        "confirm_slot_provision": "yes",
    }
    first_response = client_with_temp_db.post("/admin/slots/provision", data=data, follow_redirects=True)
    second_response = client_with_temp_db.post("/admin/slots/provision", data=data)

    assert first_response.status_code == 200
    assert b"Created 2 empty slots for case CASE-REPEAT: 2, 3." in first_response.data
    assert second_response.status_code == 200
    assert b"Slot identifiers already exist in case CASE-REPEAT: 2, 3." in second_response.data
    verify_conn = db.get_connection()
    try:
        rows = verify_conn.execute(
            "SELECT slot_position, current_asset_tag FROM slots WHERE case_name = 'CASE-REPEAT' ORDER BY slot_position;"
        ).fetchall()
        assert verify_conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0] == 0
        assert verify_conn.execute("SELECT COUNT(*) FROM slot_occupancy;").fetchone()[0] == 0
        assert verify_conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0] == 0
        assert verify_conn.execute("SELECT COUNT(*) FROM case_metadata;").fetchone()[0] == 0
    finally:
        verify_conn.close()

    assert [(int(row["slot_position"]), row["current_asset_tag"]) for row in rows] == [(1, None), (2, None), (3, None)]


def test_admin_slot_provision_requires_existing_case(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={"action": "preview", "case_number": "CASE-MISSING", "slot_identifiers": "1"},
    )

    assert response.status_code == 200
    assert b"Select an existing case before provisioning empty slots." in response.data
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM slots;").fetchone()[0] == 0
    finally:
        conn.close()


def test_admin_slot_provision_blocks_commit_when_preview_values_change(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO slots (case_name, slot_position, current_asset_tag) VALUES ('CASE-PREVIEW', 1, NULL);")
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.post(
        "/admin/slots/provision",
        data={
            "action": "commit",
            "case_number": "CASE-PREVIEW",
            "slot_identifiers": "2 3",
            "expected_case_number": "CASE-PREVIEW",
            "expected_slot_identifiers": "2",
            "confirm_slot_provision": "yes",
        },
    )

    assert response.status_code == 200
    assert b"Preview changed. Review the slot provisioning preview again before committing." in response.data
    verify_conn = db.get_connection()
    try:
        rows = verify_conn.execute("SELECT slot_position FROM slots WHERE case_name = 'CASE-PREVIEW';").fetchall()
    finally:
        verify_conn.close()
    assert [int(row["slot_position"]) for row in rows] == [1]


def test_case_correction_schema_is_append_only(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO case_correction_events (
                event_type,
                created_at,
                actor_user_id,
                actor_username,
                old_case_name,
                new_case_name,
                affected_slot_count,
                affected_asset_count
            )
            VALUES ('CASE_REMOVE', '2026-01-01T00:00:00+00:00', 1, 'admin', 'CASE-X', NULL, 1, 0);
            """
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE case_correction_events SET old_case_name = 'CASE-Y' WHERE id = 1;")
        conn.rollback()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM case_correction_events WHERE id = 1;")
    finally:
        conn.close()


def test_operator_denied_case_correction_preview_and_commit(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-case-correct", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)
    _insert_case_correction_fixture(used=False)

    entry_response = client_with_temp_db.get("/admin/case-corrections")
    preview_response = client_with_temp_db.post(
        "/admin/case-corrections",
        data={"action": "preview", "event_type": "CASE_REMOVE", "old_case_name": "CASE-OLD"},
    )
    commit_response = client_with_temp_db.post(
        "/admin/case-corrections",
        data={
            "action": "commit",
            "event_type": "CASE_REMOVE",
            "old_case_name": "CASE-OLD",
            "expected_event_type": "CASE_REMOVE",
            "expected_old_case_name": "CASE-OLD",
            "expected_new_case_name": "",
            "expected_slot_count": "2",
            "expected_asset_count": "0",
            "confirm_correction": "1",
        },
    )

    assert entry_response.status_code == 403
    assert preview_response.status_code == 403
    assert commit_response.status_code == 403
    assert _case_correction_state()["corrections"] == []


def test_case_correction_page_shows_empty_case_message(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = client_with_temp_db.get("/admin/case-corrections")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No Cases are available to correct." in html
    assert "Admin Tools → Provision Case / Slots" in html
    assert "/admin/slots/provision" in html
    assert 'name="old_case_name"' not in html
    assert 'name="new_case_name"' not in html


def test_case_correction_page_uses_case_dropdowns_and_rename_only_new_case(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_case_correction_fixture(used=False)

    response = client_with_temp_db.get("/admin/case-corrections")
    html = response.get_data(as_text=True)
    remove_section = html[html.index("Remove Never-Used Case") : html.index("Correction History")]

    assert response.status_code == 200
    assert 'id="old_case_name"' not in html
    assert 'id="rename_old_case_name" name="old_case_name" required' in html
    assert 'id="remove_old_case_name" name="old_case_name" required' in html
    assert '<option value="CASE-OLD"' in html
    assert 'id="new_case_name" name="new_case_name"' in html
    assert 'id="new_case_name" name="new_case_name" value="" autocomplete="off" required' in html
    assert 'name="new_case_name"' not in remove_section


def test_case_rename_preview_does_not_write(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_case_correction_fixture()
    before = _case_correction_state()

    response = client_with_temp_db.post(
        "/admin/case-corrections",
        data={
            "action": "preview",
            "event_type": "CASE_RENAME",
            "old_case_name": "CASE-OLD",
            "new_case_name": "CASE-NEW",
        },
    )

    assert response.status_code == 200
    assert b"Preview Correction" in response.data
    assert b'name="expected_slot_count" value="2"' in response.data
    assert b'name="expected_asset_count" value="1"' in response.data
    assert _case_correction_state() == before


def test_case_correction_page_shows_successful_history(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO case_correction_events (
                event_type,
                created_at,
                actor_user_id,
                actor_username,
                old_case_name,
                new_case_name,
                affected_slot_count,
                affected_asset_count
            )
            VALUES (
                'CASE_RENAME',
                '2026-07-29T14:03:00+00:00',
                1,
                'admin-slots',
                'CASE-OLD',
                'CASE-NEW',
                2,
                1
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.get("/admin/case-corrections")

    assert response.status_code == 200
    assert b"Correction History" in response.data
    assert b"CASE_RENAME" in response.data
    assert b"2026-07-29T14:03:00+00:00" in response.data
    assert b"admin-slots" in response.data
    assert b"CASE-OLD" in response.data
    assert b"CASE-NEW" in response.data
    assert b"<code>2</code>" in response.data
    assert b"<code>1</code>" in response.data


def test_case_rename_commit_updates_current_state_and_preserves_events(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    asset_id = _insert_case_correction_fixture()
    before = _case_correction_state()

    response = client_with_temp_db.post(
        "/admin/case-corrections",
        data={
            "action": "commit",
            "event_type": "CASE_RENAME",
            "old_case_name": "CASE-OLD",
            "new_case_name": "CASE-NEW",
            "expected_event_type": "CASE_RENAME",
            "expected_old_case_name": "CASE-OLD",
            "expected_new_case_name": "CASE-NEW",
            "expected_slot_count": "2",
            "expected_asset_count": "1",
            "confirm_correction": "1",
        },
        follow_redirects=True,
    )
    after = _case_correction_state()

    assert response.status_code == 200
    assert b"Renamed Case CASE-OLD to CASE-NEW." in response.data
    assert [(row["id"], row["case_name"]) for row in after["slots"]] == [(1901, "CASE-NEW"), (1902, "CASE-NEW")]
    assert after["assets"] == [
        {"asset_tag": "CASE-ASSET-1", "home_slot_id": 1901, "case_number": "CASE-NEW", "slot_number": "1"}
    ]
    assert after["occupancy"] == [{"slot_id": 1901, "asset_id": asset_id}]
    assert after["events"] == before["events"]
    assert after["corrections"] == [
        {
            "event_type": "CASE_RENAME",
            "actor_user_id": 1,
            "actor_username": "admin-slots",
            "old_case_name": "CASE-OLD",
            "new_case_name": "CASE-NEW",
            "affected_slot_count": 2,
            "affected_asset_count": 1,
        }
    ]


def test_case_rename_blocks_used_target_identifier(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_case_correction_fixture()
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (1910, 'CASE-USED', 1, NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.post(
        "/admin/case-corrections",
        data={
            "action": "preview",
            "event_type": "CASE_RENAME",
            "old_case_name": "CASE-OLD",
            "new_case_name": "CASE-USED",
        },
    )

    assert b"New Case identifier is already used." in response.data
    assert _case_correction_state()["corrections"] == []


def test_case_rename_blocks_stale_confirmation(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_case_correction_fixture(used=True, with_event=False)
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO assets (asset_tag, location_type, home_slot_id, case_number, slot_number)
            VALUES ('CASE-ASSET-2', 'STORAGE', 1902, 'CASE-OLD', '2');
            """
        )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.post(
        "/admin/case-corrections",
        data={
            "action": "commit",
            "event_type": "CASE_RENAME",
            "old_case_name": "CASE-OLD",
            "new_case_name": "CASE-NEW",
            "expected_event_type": "CASE_RENAME",
            "expected_old_case_name": "CASE-OLD",
            "expected_new_case_name": "CASE-NEW",
            "expected_slot_count": "2",
            "expected_asset_count": "1",
            "confirm_correction": "1",
        },
    )

    assert b"Case asset count changed. Preview again." in response.data
    state = _case_correction_state()
    assert {row["case_name"] for row in state["slots"]} == {"CASE-OLD"}
    assert state["corrections"] == []


def test_case_remove_commit_deletes_strictly_never_used_case(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_case_correction_fixture(used=False)

    response = client_with_temp_db.post(
        "/admin/case-corrections",
        data={
            "action": "commit",
            "event_type": "CASE_REMOVE",
            "old_case_name": "CASE-OLD",
            "expected_event_type": "CASE_REMOVE",
            "expected_old_case_name": "CASE-OLD",
            "expected_new_case_name": "",
            "expected_slot_count": "2",
            "expected_asset_count": "0",
            "confirm_correction": "1",
        },
        follow_redirects=True,
    )
    state = _case_correction_state()

    assert response.status_code == 200
    assert b"Removed never-used Case CASE-OLD." in response.data
    assert state["slots"] == []
    assert state["corrections"] == [
        {
            "event_type": "CASE_REMOVE",
            "actor_user_id": 1,
            "actor_username": "admin-slots",
            "old_case_name": "CASE-OLD",
            "new_case_name": None,
            "affected_slot_count": 2,
            "affected_asset_count": 0,
        }
    ]


def test_case_remove_blocks_event_history_reference(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_case_correction_fixture(used=False)
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
            VALUES ('OLD-EVENT-ASSET', 'SLOT_ASSIGN', '2026-01-01T00:00:00+00:00', 'admin', NULL, ?, NULL);
            """,
            (json.dumps({"slot": {"case_number": "CASE-OLD", "slot_number": 1}}),),
        )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.post(
        "/admin/case-corrections",
        data={"action": "preview", "event_type": "CASE_REMOVE", "old_case_name": "CASE-OLD"},
    )

    assert b"Cannot remove a Case referenced by event history." in response.data
    state = _case_correction_state()
    assert len(state["slots"]) == 2
    assert state["corrections"] == []


def test_unslotted_storage_asset_can_be_assigned_after_slot_provision(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO slots (case_name, slot_position, current_asset_tag) VALUES ('CASE-Q', 2, NULL);")
        conn.commit()
    finally:
        conn.close()

    previewed = client_with_temp_db.post(
        "/admin/slots/provision",
        data={"action": "preview", "case_number": "CASE-Q", "slot_identifiers": "1"},
    )
    assert previewed.status_code == 200

    provisioned = client_with_temp_db.post(
        "/admin/slots/provision",
        data={
            "action": "commit",
            "case_number": "CASE-Q",
            "slot_identifiers": "1",
            "expected_case_number": "CASE-Q",
            "expected_slot_identifiers": "1",
            "confirm_slot_provision": "yes",
        },
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
    assert b"SER-LIST-1" in response.data
    assert b"laptop" in response.data
    assert b'data-label="Asset tag"' in response.data
    assert b'data-label="Serial number"' in response.data
    assert b'data-label="Equipment type"' in response.data
    assert b'data-label="Action"' in response.data
    assert b"@media (max-width: 640px)" in response.data
    assert b"width: 100%" in response.data
    assert b"Assign" in response.data


def test_assign_slot_long_asset_list_collapses_and_keeps_selected_asset_visible(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    for index in range(13):
        _create_unslotted_asset(
            client_with_temp_db,
            asset_tag=f"AT-LONG-{index:03d}",
            serial_number=f"SER-LONG-{index:03d}",
            equipment_type="router" if index == 5 else "laptop",
        )

    list_response = client_with_temp_db.get("/admin/assign-slot")
    assert list_response.status_code == 200
    assert b'class="assign-slot-list-details"' in list_response.data
    assert b"Show 13 unslotted assets" in list_response.data
    assert b"SER-LONG-005" in list_response.data
    assert b"router" in list_response.data

    selected_response = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "lookup", "asset_tag": "AT-LONG-005"},
        follow_redirects=True,
    )
    assert selected_response.status_code == 200
    assert b"Selected Asset" in selected_response.data
    assert b"AT-LONG-005" in selected_response.data
    assert b"SER-LONG-005" in selected_response.data
    assert b"router" in selected_response.data
    assert b'input type="hidden" name="asset_tag" value="AT-LONG-005"' in selected_response.data
    assert b"Show 13 unslotted assets" in selected_response.data

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
    assert b"SER-SELECT-1" in response.data
    assert b"laptop" in response.data
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


def _insert_assign_slot_slots(rows: list[tuple[int, str, int, str | None]]) -> None:
    conn = db.get_connection()
    try:
        conn.executemany(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (?, ?, ?, ?);
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _assign_slot_route_state() -> dict[str, object]:
    conn = db.get_connection()
    try:
        return {
            "assets": [
                dict(row)
                for row in conn.execute(
                    "SELECT asset_tag, home_slot_id, case_number, slot_number FROM assets ORDER BY asset_tag;"
                ).fetchall()
            ],
            "slots": [
                dict(row)
                for row in conn.execute("SELECT id, current_asset_tag FROM slots ORDER BY id;").fetchall()
            ],
            "occupancy": [
                dict(row)
                for row in conn.execute("SELECT slot_id, asset_id FROM slot_occupancy ORDER BY slot_id;").fetchall()
            ],
            "slot_assign_events": [
                dict(row)
                for row in conn.execute(
                    "SELECT asset_tag, event_type FROM asset_events WHERE event_type = 'SLOT_ASSIGN' ORDER BY id;"
                ).fetchall()
            ],
        }
    finally:
        conn.close()


def test_assign_slot_workflow_accumulates_previews_confirms_and_commits_mixed_batch(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    _create_unslotted_asset(client_with_temp_db, asset_tag="AT-BATCH-LAPTOP", serial_number="SER-BATCH-LAPTOP")
    _create_unslotted_asset(
        client_with_temp_db,
        asset_tag="AT-BATCH-ROUTER",
        serial_number="SER-BATCH-ROUTER",
        equipment_type="router",
    )
    _insert_assign_slot_slots([(9001, "CASE-BATCH-UI", 1, None), (9002, "CASE-BATCH-UI", 2, None)])

    first = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "lookup", "asset_tag": "AT-BATCH-LAPTOP"},
        follow_redirects=True,
    )
    assert first.status_code == 200
    assert b"Asset AT-BATCH-LAPTOP is eligible for slot assignment." in first.data
    assert b"AT-BATCH-LAPTOP" in first.data

    duplicate = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "lookup", "asset_tag": "AT-BATCH-LAPTOP"},
        follow_redirects=True,
    )
    assert b"Asset AT-BATCH-LAPTOP is already in this assignment batch." in duplicate.data

    removed = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "remove", "remove_asset_tag": "AT-BATCH-LAPTOP"},
        follow_redirects=True,
    )
    assert b"Removed asset AT-BATCH-LAPTOP from the assignment batch." in removed.data
    assert b"No assets in the assignment batch." in removed.data

    client_with_temp_db.post("/admin/assign-slot", data={"action": "lookup", "asset_tag": "AT-BATCH-LAPTOP"})
    client_with_temp_db.post("/admin/assign-slot", data={"action": "lookup", "asset_tag": "AT-BATCH-ROUTER"})

    preview = client_with_temp_db.post(
        "/admin/assign-slot",
        data={
            "action": "preview",
            "building": "HQ",
            "room": "105",
            "case_name": "CASE-BATCH-UI",
            "slot_id": ["9001", "9002"],
            "notes": "operator batch",
        },
        follow_redirects=True,
    )
    assert preview.status_code == 200
    assert b"Assignment batch preview ready. Review and confirm one batch to commit." in preview.data
    assert b"Preview Assignment" in preview.data
    assert b"AT-BATCH-LAPTOP" in preview.data
    assert b"AT-BATCH-ROUTER" in preview.data
    assert b"CASE-BATCH-UI / Slot 1" in preview.data
    assert b"CASE-BATCH-UI / Slot 2" in preview.data
    assert b"I reviewed this assignment batch" in preview.data

    commit = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "commit", "confirm_assignment": "yes"},
        follow_redirects=True,
    )
    assert commit.status_code == 200
    assert b"Assigned 2 assets to slots in CASE-BATCH-UI." in commit.data
    assert b"No assets in the assignment batch." in commit.data

    state = _assign_slot_route_state()
    assert state["slots"] == [
        {"id": 9001, "current_asset_tag": "AT-BATCH-LAPTOP"},
        {"id": 9002, "current_asset_tag": "AT-BATCH-ROUTER"},
    ]
    assert state["slot_assign_events"] == [
        {"asset_tag": "AT-BATCH-LAPTOP", "event_type": "SLOT_ASSIGN"},
        {"asset_tag": "AT-BATCH-ROUTER", "event_type": "SLOT_ASSIGN"},
    ]


def test_assign_slot_workflow_requires_confirmation_and_is_repeat_submission_safe(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    _create_unslotted_asset(client_with_temp_db, asset_tag="AT-CONFIRM-1", serial_number="SER-CONFIRM-1")
    _insert_assign_slot_slots([(9011, "CASE-CONFIRM", 1, None)])
    client_with_temp_db.post("/admin/assign-slot", data={"action": "lookup", "asset_tag": "AT-CONFIRM-1"})
    client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "preview", "case_name": "CASE-CONFIRM", "slot_id": ["9011"]},
    )

    missing_confirmation = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "commit"},
        follow_redirects=True,
    )
    assert b"Please confirm you reviewed the assignment batch before committing." in missing_confirmation.data
    assert b'value="CASE-CONFIRM" selected' in missing_confirmation.data
    assert b'value="9011"' in missing_confirmation.data
    assert _assign_slot_route_state()["slot_assign_events"] == []

    committed = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "commit", "confirm_assignment": "yes"},
        follow_redirects=True,
    )
    assert b"Assigned asset AT-CONFIRM-1 to CASE-CONFIRM slot 1." in committed.data

    repeated = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "commit", "confirm_assignment": "yes"},
        follow_redirects=True,
    )
    assert b"Preview the complete mapping before committing." in repeated.data
    assert _assign_slot_route_state()["slot_assign_events"] == [
        {"asset_tag": "AT-CONFIRM-1", "event_type": "SLOT_ASSIGN"}
    ]


def test_assign_slot_failed_preview_clears_prior_pending_mapping(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    _create_unslotted_asset(client_with_temp_db, asset_tag="AT-PENDING-1", serial_number="SER-PENDING-1")
    _insert_assign_slot_slots([(9015, "CASE-PENDING", 1, None)])
    client_with_temp_db.post("/admin/assign-slot", data={"action": "lookup", "asset_tag": "AT-PENDING-1"})
    ready = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "preview", "case_name": "CASE-PENDING", "slot_id": ["9015"]},
        follow_redirects=True,
    )
    assert b"Assignment batch preview ready." in ready.data

    failed_preview = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "preview", "case_name": "CASE-PENDING", "slot_id": [""]},
        follow_redirects=True,
    )
    assert b"Select one empty destination slot for each asset." in failed_preview.data

    commit = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "commit", "confirm_assignment": "yes"},
        follow_redirects=True,
    )
    assert b"Preview the complete mapping before committing." in commit.data
    assert _assign_slot_route_state()["slot_assign_events"] == []

def test_assign_slot_workflow_blocks_insufficient_occupied_and_duplicate_slots(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    _create_unslotted_asset(client_with_temp_db, asset_tag="AT-BLOCK-1", serial_number="SER-BLOCK-1")
    _create_unslotted_asset(client_with_temp_db, asset_tag="AT-BLOCK-2", serial_number="SER-BLOCK-2", equipment_type="switch")
    _insert_assign_slot_slots([
        (9021, "CASE-BLOCK", 1, None),
        (9022, "CASE-BLOCK", 2, "AT-OCCUPANT"),
        (9023, "CASE-ROOM", 1, None),
        (9024, "CASE-ROOM", 2, None),
    ])
    client_with_temp_db.post("/admin/assign-slot", data={"action": "lookup", "asset_tag": "AT-BLOCK-1"})
    client_with_temp_db.post("/admin/assign-slot", data={"action": "lookup", "asset_tag": "AT-BLOCK-2"})
    before = _assign_slot_route_state()

    insufficient = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "preview", "case_name": "CASE-BLOCK", "slot_id": ["9021", "9022"]},
        follow_redirects=True,
    )
    assert b"Selected case does not have enough empty slots for this assignment batch." in insufficient.data
    assert _assign_slot_route_state() == before

    duplicate_slot = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "preview", "case_name": "CASE-ROOM", "slot_id": ["9023", "9023"]},
        follow_redirects=True,
    )
    assert b"Each destination slot may appear only once in a batch." in duplicate_slot.data
    assert _assign_slot_route_state() == before

    occupied_slot = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "preview", "case_name": "CASE-BLOCK", "slot_id": ["9022", "9021"]},
        follow_redirects=True,
    )
    assert b"Selected slot is already occupied." in occupied_slot.data
    assert _assign_slot_route_state() == before


def test_assign_slot_commit_failure_does_not_show_success_or_clear_batch(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    _create_unslotted_asset(client_with_temp_db, asset_tag="AT-STALE-1", serial_number="SER-STALE-1")
    _insert_assign_slot_slots([(9031, "CASE-STALE", 1, None)])
    client_with_temp_db.post("/admin/assign-slot", data={"action": "lookup", "asset_tag": "AT-STALE-1"})
    preview = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "preview", "case_name": "CASE-STALE", "slot_id": ["9031"]},
        follow_redirects=True,
    )
    assert b"Preview Assignment" in preview.data

    conn = db.get_connection()
    try:
        conn.execute("UPDATE slots SET current_asset_tag = 'EXISTING-OCCUPANT' WHERE id = 9031;")
        conn.commit()
    finally:
        conn.close()

    failed_commit = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "commit", "confirm_assignment": "yes"},
        follow_redirects=True,
    )
    assert b"Selected slot is already occupied." in failed_commit.data
    assert b"Assigned asset AT-STALE-1" not in failed_commit.data
    assert b"AT-STALE-1" in failed_commit.data
    assert _assign_slot_route_state()["slot_assign_events"] == []
def test_assign_slot_selectors_show_only_empty_slots_and_available_cases(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES
                (501, 'CASE-SEL', 1, 'AT-BUSY'),
                (502, 'CASE-SEL', 2, NULL),
                (503, 'CASE-FULL', 1, 'AT-FULL-1'),
                (504, 'CASE-FULL', 2, 'AT-FULL-2');
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
    assert b"CASE-SEL / Slot 1" not in lookup.data
    assert b"CASE-SEL / Slot 2" in lookup.data
    assert b'value="CASE-SEL"' in lookup.data
    assert b"CASE-FULL" not in lookup.data
    assert b" - occupied" not in lookup.data
    assert b"disabled" not in lookup.data


def test_assign_slot_selector_script_syncs_case_and_slot_choices(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    _insert_assign_slot_slots([(505, "CASE-JS-A", 1, None), (506, "CASE-JS-B", 1, None)])
    _create_unslotted_asset(client_with_temp_db, asset_tag="AT-JS-1", serial_number="SER-JS-1")

    lookup = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "lookup", "asset_tag": "AT-JS-1"},
        follow_redirects=True,
    )

    assert lookup.status_code == 200
    assert b'data-case="CASE-JS-A"' in lookup.data
    assert b'data-case="CASE-JS-B"' in lookup.data
    assert b"assignCaseSelect.value = slotCase" in lookup.data
    assert b"selectedOption.dataset.case !== selectedCase" in lookup.data

def test_assign_slot_allows_blank_building_and_room_without_default_location(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (720, 'CASE-BLANK-LOC', 1, NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()
    _create_unslotted_asset(
        client_with_temp_db,
        asset_tag="AT-BLANK-LOC",
        serial_number="SER-BLANK-LOC",
    )

    response = client_with_temp_db.post(
        "/admin/assign-slot",
        data={
            "action": "assign",
            "asset_tag": "AT-BLANK-LOC",
            "building": "",
            "room": "",
            "case_name": "CASE-BLANK-LOC",
            "slot_id": "720",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Assigned asset AT-BLANK-LOC to CASE-BLANK-LOC slot 1." in response.data
    assert b"building is required." not in response.data
    assert b"room/area is required." not in response.data
    assert b"Suffolk" not in response.data
    assert b"Base" not in response.data
    assert b"Unknown" not in response.data

    verify_conn = db.get_connection()
    try:
        asset_row = verify_conn.execute(
            "SELECT building_room, home_slot_id FROM assets WHERE asset_tag = 'AT-BLANK-LOC' LIMIT 1;"
        ).fetchone()
        event_row = verify_conn.execute(
            "SELECT payload FROM asset_events WHERE asset_tag = 'AT-BLANK-LOC' AND event_type = 'SLOT_ASSIGN' LIMIT 1;"
        ).fetchone()
    finally:
        verify_conn.close()

    assert asset_row is not None
    assert str(asset_row["building_room"] or "") == ""
    assert int(asset_row["home_slot_id"]) == 720
    assert event_row is not None
    assert json.loads(str(event_row["payload"]))["building_room"] == ""


def test_assign_slot_stores_explicit_building_and_room(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (721, 'CASE-EXPLICIT-LOC', 1, NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()
    _create_unslotted_asset(
        client_with_temp_db,
        asset_tag="AT-EXPLICIT-LOC",
        serial_number="SER-EXPLICIT-LOC",
    )

    response = client_with_temp_db.post(
        "/admin/assign-slot",
        data={
            "action": "assign",
            "asset_tag": "AT-EXPLICIT-LOC",
            "building": "HQ",
            "room": "105",
            "case_name": "CASE-EXPLICIT-LOC",
            "slot_id": "721",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Assigned asset AT-EXPLICIT-LOC to CASE-EXPLICIT-LOC slot 1." in response.data

    verify_conn = db.get_connection()
    try:
        asset_row = verify_conn.execute(
            "SELECT building_room FROM assets WHERE asset_tag = 'AT-EXPLICIT-LOC' LIMIT 1;"
        ).fetchone()
        event_row = verify_conn.execute(
            "SELECT payload FROM asset_events WHERE asset_tag = 'AT-EXPLICIT-LOC' AND event_type = 'SLOT_ASSIGN' LIMIT 1;"
        ).fetchone()
    finally:
        verify_conn.close()

    assert asset_row is not None
    assert str(asset_row["building_room"] or "") == "HQ/105"
    assert event_row is not None
    assert json.loads(str(event_row["payload"]))["building_room"] == "HQ/105"


def test_assign_slot_validation_error_preserves_submitted_location_values(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (722, 'CASE-RETAIN-LOC', 1, NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()
    _create_unslotted_asset(
        client_with_temp_db,
        asset_tag="AT-RETAIN-LOC",
        serial_number="SER-RETAIN-LOC",
    )

    response = client_with_temp_db.post(
        "/admin/assign-slot",
        data={
            "action": "assign",
            "asset_tag": "AT-RETAIN-LOC",
            "building": "Closed HQ",
            "room": "105A",
            "case_name": "CASE-RETAIN-LOC",
            "slot_id": "722",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Choose a valid building." in response.data
    assert b'<option value="Closed HQ" selected>Closed HQ</option>' in response.data
    assert b'value="105A"' in response.data
    assert b'value="CASE-RETAIN-LOC" selected' in response.data
    assert b'value="722"' in response.data


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

def test_assign_slot_dropdowns_render_cases_and_slots_in_natural_numeric_order(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _create_building("HQ")
    conn = db.get_connection()
    try:
        conn.executemany(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (?, ?, ?, NULL);
            """,
            [
                (610, "CASE-10", 10),
                (602, "CASE-2", 2),
                (609, "CASE-9", 9),
                (601, "CASE-1", 1),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    created = client_with_temp_db.post(
        "/admin/assets/new",
        data={
            "asset_tag": "AT-NATURAL-SLOT",
            "serial_number": "SER-NATURAL-SLOT",
            "manufacturer": "Dell",
            "equipment_type": "laptop",
            "building": "HQ",
            "room": "100",
        },
    )
    assert created.status_code == 302

    response = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "lookup", "asset_tag": "AT-NATURAL-SLOT"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    rendered = response.data
    case_positions = [
        rendered.index(b'<option value="CASE-1"'),
        rendered.index(b'<option value="CASE-2"'),
        rendered.index(b'<option value="CASE-9"'),
        rendered.index(b'<option value="CASE-10"'),
    ]
    slot_positions = [
        rendered.index(b"CASE-1 / Slot 1"),
        rendered.index(b"CASE-2 / Slot 2"),
        rendered.index(b"CASE-9 / Slot 9"),
        rendered.index(b"CASE-10 / Slot 10"),
    ]
    assert case_positions == sorted(case_positions)
    assert slot_positions == sorted(slot_positions)
