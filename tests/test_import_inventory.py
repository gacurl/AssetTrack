from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from scripts import import_inventory


def _write_inventory(path: Path, rows: list[dict[str, object]]) -> None:
    dataframe = pd.DataFrame(rows)
    dataframe.to_excel(path, sheet_name=import_inventory.SHEET_NAME, index=False)


def _inventory_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "clean_asset_tag": "IMPORT-100",
        "case_number": "A",
        "slot_helper": 1,
        "serial_number": "SER-100",
        "equipment_type": "laptop",
        "manufacturer": "Example",
        "model": "Model 100",
        "model_code": "M100",
        "building_room": "HQ/101",
        "slot_number": "1",
        "mac_address": "00:11:22:33:44:55",
    }
    row.update(overrides)
    return row


def _configure_import(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "assettrack.db"
    excel_path = tmp_path / "inventory.xlsx"
    db.initialize_schema(db_path)
    monkeypatch.setattr(import_inventory, "DB_PATH", db_path)
    monkeypatch.setattr(import_inventory, "EXCEL_PATH", excel_path)
    return db_path, excel_path


def test_inventory_xlsx_import_appends_events_and_reconciles_current_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path, excel_path = _configure_import(monkeypatch, tmp_path)
    _write_inventory(excel_path, [_inventory_row()])

    rows = import_inventory.load_rows()
    result = import_inventory.run_import(rows)

    assert result == (1, 1, 1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        asset = conn.execute(
            """
            SELECT id, asset_tag, home_slot_id, location_type, current_holder_id
            FROM assets
            WHERE asset_tag = 'IMPORT-100';
            """
        ).fetchone()
        assert asset is not None
        assert asset["home_slot_id"] is not None
        assert asset["location_type"] == "STORAGE"
        assert asset["current_holder_id"] is None

        slot = conn.execute(
            "SELECT current_asset_tag FROM slots WHERE id = ?;",
            (asset["home_slot_id"],),
        ).fetchone()
        assert slot is not None
        assert slot["current_asset_tag"] == "IMPORT-100"

        occupancy = conn.execute(
            """
            SELECT slot_id
            FROM slot_occupancy
            WHERE asset_id = ?;
            """,
            (asset["id"],),
        ).fetchone()
        assert occupancy is not None
        assert occupancy["slot_id"] == asset["home_slot_id"]

        events = conn.execute(
            """
            SELECT event_type, actor, notes, payload
            FROM asset_events
            WHERE asset_tag = 'IMPORT-100'
            ORDER BY id;
            """
        ).fetchall()
        assert [row["event_type"] for row in events] == ["ASSET_CREATED", "SLOT_ASSIGN"]
        assert [row["actor"] for row in events] == ["inventory_import", "inventory_import"]
        assert [row["notes"] for row in events] == ["00:11:22:33:44:55", "00:11:22:33:44:55"]

        created_payload = json.loads(events[0]["payload"])
        assert created_payload["serial_number"] == "SER-100"
        assert created_payload["building_room"] == "HQ/101"

        slot_payload = json.loads(events[1]["payload"])
        assert slot_payload == {
            "slot_id": asset["home_slot_id"],
            "case_number": "CASE-A",
            "slot_number": 1,
            "building_room": "HQ/101",
            "equipment_type": "laptop",
        }

        issue_lookup = intake_app._find_asset_for_scan_tag(conn, "IMPORT-100")
        assert issue_lookup is not None
        assert issue_lookup["asset_tag"] == "IMPORT-100"
    finally:
        conn.close()

    persisted = sqlite3.connect(db_path)
    try:
        assert persisted.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0] == 2
    finally:
        persisted.close()


def test_inventory_xlsx_import_keeps_blank_building_room_blank(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path, excel_path = _configure_import(monkeypatch, tmp_path)
    _write_inventory(excel_path, [_inventory_row(clean_asset_tag="IMPORT-BLANK-LOCATION", building_room="")])

    rows = import_inventory.load_rows()
    result = import_inventory.run_import(rows)

    assert result == (1, 1, 1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        asset = conn.execute(
            """
            SELECT building_room
            FROM assets
            WHERE asset_tag = 'IMPORT-BLANK-LOCATION';
            """
        ).fetchone()
        assert asset is not None
        assert asset["building_room"] is None

        events = conn.execute(
            """
            SELECT event_type, payload
            FROM asset_events
            WHERE asset_tag = 'IMPORT-BLANK-LOCATION'
            ORDER BY id;
            """
        ).fetchall()
        created_payload = json.loads(events[0]["payload"])
        assert "building_room" not in created_payload
        slot_payload = json.loads(events[1]["payload"])
        assert slot_payload["building_room"] == ""
        assert "Unknown" not in events[0]["payload"]
        assert "N/A" not in events[0]["payload"]
        assert "Unassigned" not in events[0]["payload"]
    finally:
        conn.close()


def test_inventory_xlsx_import_accepts_laptop_switch_and_router(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path, excel_path = _configure_import(monkeypatch, tmp_path)
    _write_inventory(
        excel_path,
        [
            _inventory_row(clean_asset_tag="IMPORT-LAPTOP", serial_number="SER-LAPTOP", equipment_type="laptop"),
            _inventory_row(clean_asset_tag="IMPORT-SWITCH", serial_number="SER-SWITCH", equipment_type="switch", slot_helper=2, slot_number="2"),
            _inventory_row(clean_asset_tag="IMPORT-ROUTER", serial_number="SER-ROUTER", equipment_type="router", slot_helper=3, slot_number="3"),
        ],
    )

    rows = import_inventory.load_rows()
    result = import_inventory.run_import(rows)

    assert result == (3, 3, 3)
    conn = sqlite3.connect(db_path)
    try:
        values = conn.execute(
            "SELECT equipment_type FROM assets ORDER BY asset_tag;"
        ).fetchall()
        assert [row[0] for row in values] == ["laptop", "router", "switch"]
    finally:
        conn.close()


def test_inventory_xlsx_import_rejects_unsupported_equipment_type_before_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path, excel_path = _configure_import(monkeypatch, tmp_path)
    _write_inventory(excel_path, [_inventory_row(equipment_type="monitor")])

    with pytest.raises(import_inventory.ImportStopError) as excinfo:
        import_inventory.load_rows()

    assert "Supported asset types are Laptop, Switch, and Router." in str(excinfo.value)
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0] == 0
    finally:
        conn.close()


def test_inventory_import_rolls_back_current_state_and_events_together(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path, excel_path = _configure_import(monkeypatch, tmp_path)
    _write_inventory(
        excel_path,
        [
            _inventory_row(),
            _inventory_row(serial_number="SER-SECOND"),
        ],
    )

    rows = import_inventory.load_rows()
    with pytest.raises(import_inventory.ImportStopError):
        import_inventory.run_import(rows)

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM slots;").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM slot_occupancy;").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0] == 0
    finally:
        conn.close()
