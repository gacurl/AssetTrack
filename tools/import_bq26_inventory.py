# file: tools/import_bq26_inventory.py

import sqlite3
from datetime import datetime, timezone
import pandas as pd

DB_PATH = "data/assettrack.db"
EXCEL_PATH = "data/import/BQ26 ETP.xlsx"
SHEET_NAME = "BQ26 main inventory data"

def as_text(v):
    if pd.isna(v):
        return ""
    return str(v).strip()

def main():
    df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, engine="openpyxl")

    now = datetime.now(timezone.utc).isoformat()

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys=ON;")

    inserted_assets = 0
    inserted_slots = 0

    with con:
        for _, r in df.iterrows():

            asset_tag = as_text(r["clean_asset_tag"])
            if not asset_tag:
                continue

            case_number = as_text(r["case_number"])
            slot_position = int(r["slot_helper"])
            case_name = f"CASE-{case_number}"

            serial_number = as_text(r["serial_number"])
            equipment_type = as_text(r["equipment_type"])
            manufacturer = as_text(r["manufacturer"])
            model = as_text(r["model"])
            model_code = as_text(r["model_code"])
            building_room = as_text(r["building_room"])
            slot_number = as_text(r["slot_number"])
            mac_address = as_text(r["mac_address"])

            notes = f"MAC: {mac_address}" if mac_address else None

            con.execute("""
                INSERT INTO assets (
                    asset_tag,
                    serial_number,
                    equipment_type,
                    manufacturer,
                    model,
                    model_code,
                    custody_state,
                    accountability_status,
                    condition,
                    building_room,
                    case_number,
                    slot_number,
                    created_date,
                    location_type,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                asset_tag,
                serial_number or None,
                equipment_type or "laptop",
                manufacturer or None,
                model or None,
                model_code or None,
                "IN_STOCK",
                "OK",
                "GOOD",
                building_room or None,
                case_number or None,
                slot_number or None,
                now,
                "STORAGE",
                notes
            ))

            inserted_assets += 1

            con.execute("""
                INSERT INTO slots (
                    case_name,
                    slot_position,
                    current_asset_tag
                )
                VALUES (?, ?, ?)
            """, (
                case_name,
                slot_position,
                asset_tag
            ))

            inserted_slots += 1

    con.close()

    print(f"Imported assets: {inserted_assets}")
    print(f"Imported slots:  {inserted_slots}")

if __name__ == "__main__":
    main()