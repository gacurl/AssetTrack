from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from assettrack.audit import record_event
from assettrack.db import assert_schema_present

DB_PATH = Path("data/assettrack.db")
EXCEL_PATH = Path("data/import/BQ26_ETP.xlsx")
SHEET_NAME = "BQ26 main inventory data"

REQUIRED_COLUMNS = {
    "clean_asset_tag",
    "case_number",
    "slot_helper",
    "serial_number",
    "equipment_type",
    "manufacturer",
    "model",
    "model_code",
    "building_room",
    "slot_number",
    "mac_address",
}


@dataclass(frozen=True)
class ImportRow:
    row_number: int
    asset_tag: str
    case_name: str
    case_number: str
    slot_position: int
    slot_number: str
    serial_number: str
    equipment_type: str
    manufacturer: str
    model: str
    model_code: str
    building_room: str
    mac_address: str


class ImportStopError(RuntimeError):
    pass


def as_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def parse_slot_position(raw_value: object, row_number: int, asset_tag: str, case_number: str, slot_number: str) -> int:
    value = as_text(raw_value)
    if not value:
        raise ImportStopError(
            "Missing slot_helper.\n"
            f"row_number={row_number}\n"
            f"asset_tag={asset_tag}\n"
            f"case_number={case_number}\n"
            f"slot_number={slot_number}"
        )
    try:
        return int(float(value))
    except ValueError as exc:
        raise ImportStopError(
            "Invalid slot_helper; expected numeric value.\n"
            f"row_number={row_number}\n"
            f"asset_tag={asset_tag}\n"
            f"case_number={case_number}\n"
            f"slot_number={slot_number}\n"
            f"slot_helper={value}"
        ) from exc


def load_rows() -> list[ImportRow]:
    if not EXCEL_PATH.exists():
        raise ImportStopError(f"Spreadsheet not found: {EXCEL_PATH}")

    dataframe = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, engine="openpyxl")
    missing_columns = sorted(REQUIRED_COLUMNS - set(dataframe.columns))
    if missing_columns:
        raise ImportStopError(f"Missing required spreadsheet columns: {', '.join(missing_columns)}")

    prepared: list[ImportRow] = []
    seen_slots: dict[tuple[str, int], tuple[str, int, str, str]] = {}

    for index, row in dataframe.iterrows():
        row_number = int(index) + 2

        asset_tag = as_text(row["clean_asset_tag"])
        if not asset_tag:
            continue

        case_number = as_text(row["case_number"])
        slot_number = as_text(row["slot_number"])
        if not case_number:
            raise ImportStopError(
                "Missing case_number.\n"
                f"row_number={row_number}\n"
                f"asset_tag={asset_tag}\n"
                "case_number=\n"
                f"slot_number={slot_number}"
            )

        slot_position = parse_slot_position(
            row["slot_helper"],
            row_number=row_number,
            asset_tag=asset_tag,
            case_number=case_number,
            slot_number=slot_number,
        )
        case_name = f"CASE-{case_number}"

        slot_key = (case_name, slot_position)
        previous = seen_slots.get(slot_key)
        if previous is not None and previous[0] != asset_tag:
            raise ImportStopError(
                "Duplicate slot assignment detected in spreadsheet.\n"
                f"row_number={row_number}\n"
                f"asset_tag={asset_tag}\n"
                f"case_number={case_number}\n"
                f"slot_number={slot_number}\n"
                f"conflicts_with_row={previous[1]}\n"
                f"conflicts_with_asset_tag={previous[0]}"
            )
        seen_slots[slot_key] = (asset_tag, row_number, case_number, slot_number)

        prepared.append(
            ImportRow(
                row_number=row_number,
                asset_tag=asset_tag,
                case_name=case_name,
                case_number=case_number,
                slot_position=slot_position,
                slot_number=slot_number,
                serial_number=as_text(row["serial_number"]),
                equipment_type=as_text(row["equipment_type"]),
                manufacturer=as_text(row["manufacturer"]),
                model=as_text(row["model"]),
                model_code=as_text(row["model_code"]),
                building_room=as_text(row["building_room"]),
                mac_address=as_text(row["mac_address"]),
            )
        )

    return prepared


def run_import(rows: list[ImportRow]) -> tuple[int, int, int]:
    now_iso = datetime.now(timezone.utc).isoformat()
    inserted_slots = 0
    inserted_assets = 0
    inserted_occupancy = 0

    assert_schema_present(DB_PATH)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON;")
        with connection:
            # Enforce physical uniqueness for slot identity.
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_slots_unique
                ON slots(case_name, slot_position);
                """
            )

            for row in rows:
                slot_insert = connection.execute(
                    """
                    INSERT OR IGNORE INTO slots (case_name, slot_position)
                    VALUES (?, ?);
                    """,
                    (row.case_name, row.slot_position),
                )
                if int(slot_insert.rowcount or 0) == 1:
                    inserted_slots += 1

                slot_row = connection.execute(
                    """
                    SELECT id
                    FROM slots
                    WHERE case_name = ? AND slot_position = ?;
                    """,
                    (row.case_name, row.slot_position),
                ).fetchone()
                if slot_row is None:
                    raise ImportStopError(
                        "Could not resolve slot id after insert.\n"
                        f"row_number={row.row_number}\n"
                        f"asset_tag={row.asset_tag}\n"
                        f"case_number={row.case_number}\n"
                        f"slot_number={row.slot_number}"
                    )

                slot_id = int(slot_row["id"])
                notes = row.mac_address or None

                connection.execute(
                    """
                    INSERT INTO assets (
                        asset_tag,
                        serial_number,
                        equipment_type,
                        manufacturer,
                        model,
                        model_code,
                        building_room,
                        home_slot_id,
                        custody_state,
                        accountability_status,
                        condition,
                        created_date,
                        location_type,
                        notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        row.asset_tag,
                        row.serial_number or None,
                        row.equipment_type or None,
                        row.manufacturer or None,
                        row.model or None,
                        row.model_code or None,
                        row.building_room or None,
                        slot_id,
                        "IN_STORAGE",
                        "OK",
                        "GOOD",
                        now_iso,
                        "STORAGE",
                        notes,
                    ),
                )
                inserted_assets += 1

                asset_row = connection.execute(
                    """
                    SELECT id
                    FROM assets
                    WHERE asset_tag = ?;
                    """,
                    (row.asset_tag,),
                ).fetchone()
                if asset_row is None:
                    raise ImportStopError(
                        "Could not resolve asset id after insert.\n"
                        f"row_number={row.row_number}\n"
                        f"asset_tag={row.asset_tag}\n"
                        f"case_number={row.case_number}\n"
                        f"slot_number={row.slot_number}"
                    )

                try:
                    connection.execute(
                        """
                        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
                        VALUES (?, ?, ?);
                        """,
                        (slot_id, int(asset_row["id"]), now_iso),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ImportStopError(
                        "Slot occupancy constraint conflict during import.\n"
                        f"row_number={row.row_number}\n"
                        f"asset_tag={row.asset_tag}\n"
                        f"case_number={row.case_number}\n"
                        f"slot_number={row.slot_number}"
                    ) from exc
                inserted_occupancy += 1

                connection.execute(
                    """
                    UPDATE slots
                    SET current_asset_tag = ?
                    WHERE id = ?;
                    """,
                    (row.asset_tag, slot_id),
                )

                created_payload = {
                    "equipment_type": row.equipment_type,
                    "serial_number": row.serial_number,
                    "manufacturer": row.manufacturer,
                    "model": row.model,
                    "model_code": row.model_code,
                    "building_room": row.building_room,
                }
                record_event(
                    connection,
                    asset_tag=row.asset_tag,
                    event_type="ASSET_CREATED",
                    event_date=now_iso,
                    actor="inventory_import",
                    notes=notes,
                    payload={key: value for key, value in created_payload.items() if value},
                )
                record_event(
                    connection,
                    asset_tag=row.asset_tag,
                    event_type="SLOT_ASSIGN",
                    event_date=now_iso,
                    actor="inventory_import",
                    notes=notes,
                    payload={
                        "slot_id": slot_id,
                        "case_number": row.case_name,
                        "slot_number": row.slot_position,
                        "building_room": row.building_room,
                        "equipment_type": row.equipment_type,
                    },
                )
    except sqlite3.IntegrityError as exc:
        raise ImportStopError(
            "Schema constraint conflict while importing. "
            "Check duplicate asset tags or slot uniqueness conflicts."
        ) from exc
    finally:
        connection.close()

    return inserted_slots, inserted_assets, inserted_occupancy


def main() -> int:
    try:
        rows = load_rows()
        inserted_slots, inserted_assets, inserted_occupancy = run_import(rows)
    except ImportStopError as exc:
        print(f"IMPORT STOPPED: {exc}", file=sys.stderr)
        return 1

    print(f"Rows processed:  {len(rows)}")
    print(f"Inserted slots:  {inserted_slots}")
    print(f"Inserted assets: {inserted_assets}")
    print(f"Inserted slot occupancy: {inserted_occupancy}")
    print()
    print("Verification:")
    print("SELECT COUNT(*) FROM assets WHERE home_slot_id IS NULL;")
    print("Expected result: 0")
    print("SELECT COUNT(*) FROM slot_occupancy;")
    print("Expected result: equals assets count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
