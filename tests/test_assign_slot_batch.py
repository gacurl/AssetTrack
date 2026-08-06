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


def _insert_slot(slot_id: int, case_name: str, position: int, current_asset_tag: str | None = None) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (?, ?, ?, ?);
            """,
            (slot_id, case_name, position, current_asset_tag),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_asset(asset_tag: str, *, equipment_type: str = "laptop", location_type: str = "STORAGE") -> int:
    conn = db.get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO assets (
                asset_tag, serial_number, equipment_type, manufacturer, building, room,
                building_room, custody_state, accountability_status, condition,
                created_date, updated_date, location_type, current_holder_id, home_slot_id
            )
            VALUES (?, ?, ?, 'Dell', 'HQ', '100', 'HQ/100', 'in_stock', 'accountable',
                    'serviceable', '2026-01-01', '2026-01-01T00:00:00Z', ?, NULL, NULL);
            """,
            (asset_tag, f"SER-{asset_tag}", equipment_type, location_type),
        )
        conn.execute(
            """
            INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
            VALUES (?, 'ASSET_CREATED', '2026-01-01T00:00:00Z', 'admin', NULL, NULL, NULL);
            """,
            (asset_tag,),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _batch(assignments: list[dict]) -> list[dict]:
    conn = db.get_connection()
    try:
        return intake_app._assign_slot_batch(
            conn,
            assignments,
            actor="admin",
            notes="batch assign",
            event_date="2026-02-01T00:00:00+00:00",
        )
    finally:
        conn.close()


def _state() -> dict[str, object]:
    conn = db.get_connection()
    try:
        return {
            "assets": [dict(row) for row in conn.execute("SELECT asset_tag, home_slot_id, case_number, slot_number FROM assets ORDER BY asset_tag;").fetchall()],
            "slots": [dict(row) for row in conn.execute("SELECT id, current_asset_tag FROM slots ORDER BY id;").fetchall()],
            "occupancy": [dict(row) for row in conn.execute("SELECT slot_id, asset_id FROM slot_occupancy ORDER BY slot_id;").fetchall()],
            "events": [dict(row) for row in conn.execute("SELECT asset_tag, event_type, event_date, payload FROM asset_events ORDER BY id;").fetchall()],
        }
    finally:
        conn.close()


def _slot_assign_events(asset_tag: str) -> list[dict]:
    conn = db.get_connection()
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT event_type, event_date, payload
                FROM asset_events
                WHERE asset_tag = ? AND event_type = 'SLOT_ASSIGN'
                ORDER BY id;
                """,
                (asset_tag,),
            ).fetchall()
        ]
    finally:
        conn.close()


def test_batch_assigns_laptop_and_network_asset_to_distinct_empty_slots(client_with_temp_db) -> None:
    _insert_slot(101, "CASE-BATCH", 1)
    _insert_slot(102, "CASE-BATCH", 2)
    laptop_id = _insert_asset("BATCH-LAPTOP", equipment_type="laptop")
    router_id = _insert_asset("BATCH-ROUTER", equipment_type="router")

    result = _batch(
        [
            {"asset_tag": "BATCH-LAPTOP", "case_name": "CASE-BATCH", "slot_id": 101, "building": "HQ", "room": "100"},
            {"asset_tag": "BATCH-ROUTER", "case_name": "CASE-BATCH", "slot_id": 102, "building": "HQ", "room": "101"},
        ]
    )

    assert [(row["asset_tag"], row["slot_id"]) for row in result] == [("BATCH-LAPTOP", 101), ("BATCH-ROUTER", 102)]
    state = _state()
    assert state["occupancy"] == [{"slot_id": 101, "asset_id": laptop_id}, {"slot_id": 102, "asset_id": router_id}]
    assert state["slots"] == [{"id": 101, "current_asset_tag": "BATCH-LAPTOP"}, {"id": 102, "current_asset_tag": "BATCH-ROUTER"}]
    assert [row["event_type"] for row in _slot_assign_events("BATCH-LAPTOP")] == ["SLOT_ASSIGN"]
    router_event = _slot_assign_events("BATCH-ROUTER")[0]
    assert json.loads(router_event["payload"])["slot_id"] == 102


@pytest.mark.parametrize("equipment_type", ["switch", "router", "server", "firewall", "ntp", "kvm", "storage"])
def test_batch_assignment_reuses_storage_eligibility_for_network_equipment(client_with_temp_db, equipment_type: str) -> None:
    _insert_slot(200, f"CASE-{equipment_type.upper()}", 1)
    _insert_asset(f"ASSET-{equipment_type.upper()}", equipment_type=equipment_type)

    _batch([{"asset_tag": f"ASSET-{equipment_type.upper()}", "case_name": f"CASE-{equipment_type.upper()}", "slot_id": 200}])

    state = _state()
    assert state["slots"] == [{"id": 200, "current_asset_tag": f"ASSET-{equipment_type.upper()}"}]
    assert [row["event_type"] for row in _slot_assign_events(f"ASSET-{equipment_type.upper()}")] == ["SLOT_ASSIGN"]


@pytest.mark.parametrize(
    ("assignments", "expected"),
    [
        ([], "Batch assignment requires at least one assignment."),
        ([{"asset_tag": "MISSING", "case_name": "CASE-V", "slot_id": 301}], "asset_tag not found"),
        ([{"asset_tag": "VALID-1", "case_name": "CASE-V", "slot_id": 999}], "Selected slot does not exist."),
        ([{"asset_tag": "VALID-1", "case_name": "CASE-OTHER", "slot_id": 301}], "Selected slot does not belong to selected case."),
        ([{"asset_tag": "VALID-1", "case_name": "CASE-V", "slot_id": 301}, {"asset_tag": "VALID-1", "case_name": "CASE-V", "slot_id": 302}], "Each asset may appear only once in a batch."),
        ([{"asset_tag": "VALID-1", "case_name": "CASE-V", "slot_id": 301}, {"asset_tag": "VALID-2", "case_name": "CASE-V", "slot_id": 301}], "Each destination slot may appear only once in a batch."),
    ],
)
def test_batch_validation_rejects_complete_batch_without_writes(client_with_temp_db, assignments: list[dict], expected: str) -> None:
    _insert_slot(301, "CASE-V", 1)
    _insert_slot(302, "CASE-V", 2)
    _insert_asset("VALID-1")
    _insert_asset("VALID-2")
    before = _state()

    with pytest.raises(ValueError, match=expected):
        _batch(assignments)

    assert _state() == before


def test_batch_rejects_ineligible_asset_without_writes(client_with_temp_db) -> None:
    _insert_slot(401, "CASE-INELIGIBLE", 1)
    _insert_asset("IN-CUSTODY-1", location_type="IN_CUSTODY")
    before = _state()

    with pytest.raises(ValueError, match="Asset must be location_type=STORAGE"):
        _batch([{"asset_tag": "IN-CUSTODY-1", "case_name": "CASE-INELIGIBLE", "slot_id": 401}])

    assert _state() == before


def test_batch_rejects_occupied_slot_and_preserves_existing_occupant(client_with_temp_db) -> None:
    _insert_slot(501, "CASE-OCC", 1, current_asset_tag="OCCUPANT")
    occupant_id = _insert_asset("OCCUPANT")
    _insert_asset("NEW-ASSET")
    assert occupant_id is not None
    before = _state()

    with pytest.raises(ValueError, match="Selected slot is already occupied"):
        _batch([{"asset_tag": "NEW-ASSET", "case_name": "CASE-OCC", "slot_id": 501}])

    assert _state() == before


def test_batch_rolls_back_occupancy_and_events_after_occupancy_write_failure(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _insert_slot(601, "CASE-FAIL-OCC", 1)
    _insert_slot(602, "CASE-FAIL-OCC", 2)
    _insert_asset("FAIL-OCC-1")
    _insert_asset("FAIL-OCC-2")
    original = intake_app._write_assign_slot_occupancy_in_tx
    calls = {"count": 0}

    def fail_second(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("forced occupancy failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(intake_app, "_write_assign_slot_occupancy_in_tx", fail_second)

    with pytest.raises(RuntimeError, match="forced occupancy failure"):
        _batch([
            {"asset_tag": "FAIL-OCC-1", "case_name": "CASE-FAIL-OCC", "slot_id": 601},
            {"asset_tag": "FAIL-OCC-2", "case_name": "CASE-FAIL-OCC", "slot_id": 602},
        ])

    state = _state()
    assert state["occupancy"] == []
    assert [row for row in state["events"] if row["event_type"] == "SLOT_ASSIGN"] == []
    assert all(row["current_asset_tag"] is None for row in state["slots"])


def test_batch_rolls_back_occupancy_and_events_after_event_write_failure(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _insert_slot(701, "CASE-FAIL-EVENT", 1)
    _insert_slot(702, "CASE-FAIL-EVENT", 2)
    _insert_asset("FAIL-EVENT-1")
    _insert_asset("FAIL-EVENT-2")
    original = intake_app._append_slot_assign_event_in_tx
    calls = {"count": 0}

    def fail_second(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("forced event failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(intake_app, "_append_slot_assign_event_in_tx", fail_second)

    with pytest.raises(RuntimeError, match="forced event failure"):
        _batch([
            {"asset_tag": "FAIL-EVENT-1", "case_name": "CASE-FAIL-EVENT", "slot_id": 701},
            {"asset_tag": "FAIL-EVENT-2", "case_name": "CASE-FAIL-EVENT", "slot_id": 702},
        ])

    state = _state()
    assert state["occupancy"] == []
    assert [row for row in state["events"] if row["event_type"] == "SLOT_ASSIGN"] == []
    assert all(row["current_asset_tag"] is None for row in state["slots"])


def test_repeated_batch_submission_does_not_duplicate_effects_or_events(client_with_temp_db) -> None:
    _insert_slot(801, "CASE-REPEAT", 1)
    _insert_slot(802, "CASE-REPEAT", 2)
    _insert_asset("REPEAT-1")
    _insert_asset("REPEAT-2")
    assignments = [
        {"asset_tag": "REPEAT-1", "case_name": "CASE-REPEAT", "slot_id": 801},
        {"asset_tag": "REPEAT-2", "case_name": "CASE-REPEAT", "slot_id": 802},
    ]

    _batch(assignments)
    after_first = _state()
    with pytest.raises(ValueError, match="Asset is already slotted"):
        _batch(assignments)

    assert _state() == after_first
    assert len(_slot_assign_events("REPEAT-1")) == 1
    assert len(_slot_assign_events("REPEAT-2")) == 1


def test_existing_assign_slot_route_authorization_and_single_assignment_still_work(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-assign-slot-boundary", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)
    assert client_with_temp_db.get("/admin/assign-slot").status_code == 403

    admin_id = create_test_user(username="admin-assign-slot-boundary", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)
    _insert_slot(901, "CASE-ROUTE", 1)
    _insert_asset("ROUTE-LAPTOP", equipment_type="laptop")

    response = client_with_temp_db.post(
        "/admin/assign-slot",
        data={"action": "assign", "asset_tag": "ROUTE-LAPTOP", "case_name": "CASE-ROUTE", "slot_id": "901"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Assigned asset ROUTE-LAPTOP to CASE-ROUTE slot 1." in response.data
    assert len(_slot_assign_events("ROUTE-LAPTOP")) == 1