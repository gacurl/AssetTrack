from __future__ import annotations

import io
import re
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd
import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.import_analysis import analyze_asset_import_csv, analyze_asset_import_xlsx
from assettrack.import_reconciliation import build_asset_import_preview
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.close()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def _login_admin(client) -> None:
    admin_id = create_test_user(username="admin-asset-import", password="admin-pass", role="admin")
    login_session(client, admin_id)


def _table_counts() -> dict[str, int]:
    conn = db.get_connection()
    try:
        return {
            "assets": int(conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0]),
            "asset_events": int(conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0]),
            "slot_occupancy": int(conn.execute("SELECT COUNT(*) FROM slot_occupancy;").fetchone()[0]),
        }
    finally:
        conn.close()


def _post_file(client, content: bytes, filename: str):
    before = _table_counts()
    response = client.post(
        "/admin/assets/import",
        data={"asset_file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )
    after = _table_counts()
    assert after == before
    return response


def _details_tag(html: str, section_id: str) -> str:
    match = re.search(rf'<details[^>]+id="{re.escape(section_id)}"[^>]*>', html)
    assert match is not None
    return match.group(0)


def _insert_slot(
    *,
    slot_id: int,
    case_name: str,
    slot_position: int,
    current_asset_tag: str | None = None,
) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (?, ?, ?, ?);
            """,
            (slot_id, case_name, slot_position, current_asset_tag),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_asset(
    *,
    asset_tag: str,
    serial_number: str = "",
    equipment_type: str = "laptop",
    manufacturer: str = "",
    model: str = "",
    model_code: str = "",
    building: str = "",
    building_room: str = "",
    case_number: str = "",
    slot_number: str = "",
    notes: str = "",
    home_slot_id: int | None = None,
    slotted: bool = False,
) -> None:
    conn = db.get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO assets (
                asset_tag,
                serial_number,
                equipment_type,
                manufacturer,
                model,
                model_code,
                building,
                building_room,
                custody_state,
                accountability_status,
                condition,
                created_date,
                location_type,
                current_holder_id,
                home_slot_id,
                case_number,
                slot_number,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'in_stock', 'accountable', 'serviceable',
                    '2026-01-01', 'STORAGE', NULL, ?, ?, ?, ?);
            """,
            (
                asset_tag,
                serial_number,
                equipment_type,
                manufacturer,
                model,
                model_code,
                building,
                building_room,
                home_slot_id,
                case_number,
                slot_number,
                notes,
            ),
        )
        if slotted and home_slot_id is not None:
            conn.execute(
                """
                INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
                VALUES (?, ?, '2026-01-01T00:00:00Z');
                """,
                (home_slot_id, int(cursor.lastrowid)),
            )
        conn.commit()
    finally:
        conn.close()


def _xlsx_bytes(rows: list[dict[str, object]] | None = None) -> bytes:
    if rows is None:
        rows = [
            {
                "clean_asset_tag": "LAP-100",
                "serial_number": "SN-LAP-100",
                "equipment_type": "laptop",
                "manufacturer": "",
                "model": "Latitude",
            },
            {
                "clean_asset_tag": "SW-100",
                "serial_number": "SN-SW-100",
                "equipment_type": "switch",
                "manufacturer": "Cisco",
                "model": "Catalyst",
            },
            {
                "clean_asset_tag": "RTR-100",
                "serial_number": "SN-RTR-100",
                "equipment_type": "router",
                "manufacturer": "Juniper",
                "model": "MX",
            },
        ]
    columns = [
        "clean_asset_tag",
        "serial_number",
        "equipment_type",
        "manufacturer",
        "model",
        "model_code",
        "building_room",
        "location_building",
        "case_identifier",
        "slot_identifier",
        "notes_comments",
    ]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(rows, columns=columns).to_excel(
            writer,
            index=False,
        )
    return buffer.getvalue()


def test_csv_and_xlsx_use_equivalent_canonical_analysis_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "assets.csv"
    csv_path.write_text(
        " Asset Tag ,Serial Number,Equipment Type,Manufacturer,Model,Location Building,Case Identifier,Slot Identifier,Notes Comments\n"
        " lap-100 , SN-LAP-100 , Laptop , , Latitude , , , ,\n"
        " sw-100 , SN-SW-100 , Switch , Cisco , Catalyst , HQ , Case-Net , 2 , Reviewed\n",
        encoding="utf-8",
    )
    xlsx_path = tmp_path / "assets.xlsx"
    rows = [
        {
            "clean_asset_tag": " lap-100 ",
            "serial_number": "SN-LAP-100",
            "equipment_type": " Laptop ",
            "manufacturer": "",
            "model": "Latitude",
        },
        {
            "clean_asset_tag": "SW-100",
            "serial_number": "SN-SW-100",
            "equipment_type": "Switch",
            "manufacturer": "Cisco",
            "model": "Catalyst",
            "location_building": "HQ",
            "case_identifier": "Case-Net",
            "slot_identifier": "2",
            "notes_comments": "Reviewed",
        },
    ]
    xlsx_path.write_bytes(_xlsx_bytes(rows))

    csv_analysis = analyze_asset_import_csv(csv_path, filename="assets.csv")
    xlsx_analysis = analyze_asset_import_xlsx(xlsx_path, filename="assets.xlsx")

    csv_rows = csv_analysis.rows
    xlsx_rows = xlsx_analysis.rows
    assert [row.asset_tag for row in csv_rows] == [row.asset_tag for row in xlsx_rows] == ["LAP-100", "SW-100"]
    assert [row.equipment_type for row in csv_rows] == [row.equipment_type for row in xlsx_rows] == ["laptop", "switch"]
    assert [row.storage_intent for row in csv_rows] == [row.storage_intent for row in xlsx_rows] == [
        "unslotted",
        "slotted",
    ]
    assert csv_rows[0].manufacturer == xlsx_rows[0].manufacturer == ""
    assert csv_rows[0].building_room == xlsx_rows[0].building_room == ""
    assert csv_analysis.equipment_types == xlsx_analysis.equipment_types == ["Laptop", "Switch"]


def test_admin_can_open_asset_import_upload_page(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = client_with_temp_db.get("/admin/assets/import")

    assert response.status_code == 200
    assert b"Admin: Import Assets" in response.data
    assert b"Analyze Import" in response.data
    assert b".csv" in response.data
    assert b".xlsx" in response.data
    assert b"Required column: <code>equipment_type</code>" in response.data
    assert b"Required identity: <code>asset_tag</code> or <code>barcode</code>" in response.data
    assert b"Supported equipment types: Laptop, Switch, Router." in response.data
    assert b"Extra columns are ignored and reported." in response.data
    assert b"clean_asset_tag" not in response.data
    assert b"python scripts/" not in response.data


def test_csv_upload_analyzes_laptop_switch_and_router_without_database_writes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    csv_content = (
        "asset_tag,barcode,serial_number,equipment_type,manufacturer,model,location_building,"
        "case_identifier,slot_identifier,notes_comments\n"
        "LAP-100,,SN-LAP-100,laptop,,Latitude,,,,\n"
        "SW-100,,SN-SW-100,switch,Cisco,Catalyst,,,,\n"
        "RTR-100,,SN-RTR-100,router,Juniper,MX,,,,\n"
    ).encode()

    response = _post_file(client_with_temp_db, csv_content, "assets.csv")

    assert response.status_code == 200
    assert b"Asset import preview complete. No database changes were made." in response.data
    assert b"Preview generated successfully. No database changes were made." in response.data
    assert b"Laptop" in response.data
    assert b"Switch" in response.data
    assert b"Router" in response.data


def test_xlsx_upload_analyzes_laptop_switch_and_router_without_database_writes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(client_with_temp_db, _xlsx_bytes(), "inventory.xlsx")

    assert response.status_code == 200
    assert b"Asset import preview complete. No database changes were made." in response.data
    assert b"XLSX" in response.data
    assert b"Laptop" in response.data
    assert b"Switch" in response.data
    assert b"Router" in response.data


def test_asset_import_preview_classifies_new_asset_with_available_slot(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=501, case_name="CASE-NEW", slot_position=1)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,manufacturer,model,case_identifier,slot_identifier\n"
        b"NEW-100,SER-NEW-100,laptop,Dell,Latitude,CASE-NEW,1\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"New Asset: 1" in response.data
    assert b"New Laptop asset with available storage." in response.data
    assert b"location_type</code>: STORAGE" in response.data
    assert b"condition</code>: serviceable" in response.data


def test_asset_import_preview_classifies_unchanged_exact_match_without_changes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=502, case_name="CASE-EXACT", slot_position=2, current_asset_tag="EXACT-100")
    _insert_asset(
        asset_tag="EXACT-100",
        serial_number="SER-EXACT-100",
        equipment_type="switch",
        manufacturer="Cisco",
        model="Catalyst",
        model_code="9300",
        building="HQ",
        building_room="HQ/101",
        case_number="CASE-EXACT",
        slot_number="2",
        home_slot_id=502,
        slotted=True,
    )

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,manufacturer,model,model_code,location_building,"
        b"building_room,case_identifier,slot_identifier\n"
        b"EXACT-100,SER-EXACT-100,switch,Cisco,Catalyst,9300,HQ,HQ/101,CASE-EXACT,2\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Unchanged Exact Match: 1" in response.data
    assert b"Upload row matches current asset data exactly." in response.data
    assert b"Proposed Update: 0" in response.data
    assert b"Existing asset has proposed field updates." not in response.data


def test_existing_slotted_asset_with_omitted_storage_preserves_current_slot(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=520, case_name="CASE-KEEP", slot_position=1, current_asset_tag="KEEP-100")
    _insert_asset(
        asset_tag="KEEP-100",
        serial_number="SER-KEEP-100",
        equipment_type="laptop",
        manufacturer="Dell",
        model="Latitude",
        building="HQ",
        building_room="HQ/101",
        case_number="CASE-KEEP",
        slot_number="1",
        home_slot_id=520,
        slotted=True,
    )

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,equipment_type\nKEEP-100,laptop\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Unchanged Exact Match: 1" in response.data
    assert b"Unslotted Import: 0" in response.data
    assert b"home_slot" not in response.data
    assert b"Storage will remain Unslotted." not in response.data


def test_existing_slotted_asset_with_blank_storage_preserves_current_slot(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=521, case_name="CASE-BLANK", slot_position=2, current_asset_tag="BLANK-100")
    _insert_asset(
        asset_tag="BLANK-100",
        serial_number="SER-BLANK-100",
        equipment_type="switch",
        manufacturer="Cisco",
        model="Catalyst",
        case_number="CASE-BLANK",
        slot_number="2",
        home_slot_id=521,
        slotted=True,
    )

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,manufacturer,model,case_identifier,slot_identifier\n"
        b"BLANK-100,SER-BLANK-100,switch,Cisco,Catalyst,,\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Unchanged Exact Match: 1" in response.data
    assert b"Unslotted Import: 0" in response.data
    assert b"Storage will remain Unslotted." not in response.data


def test_existing_unslotted_asset_with_blank_storage_is_unchanged_exact_match(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_asset(
        asset_tag="UNSLOTTED-EXACT",
        serial_number="SER-UNSLOTTED-EXACT",
        equipment_type="router",
        manufacturer="Juniper",
        model="MX",
    )

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,manufacturer,model,case_identifier,slot_identifier\n"
        b"UNSLOTTED-EXACT,SER-UNSLOTTED-EXACT,router,Juniper,MX,,\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Unchanged Exact Match: 1" in response.data
    assert b"Unslotted Import: 0" in response.data


def test_existing_asset_omitted_optional_fields_preserve_current_values(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=522, case_name="CASE-OPTIONAL", slot_position=3, current_asset_tag="OPTIONAL-100")
    _insert_asset(
        asset_tag="OPTIONAL-100",
        serial_number="SER-OPTIONAL-100",
        equipment_type="laptop",
        manufacturer="Dell",
        model="Latitude",
        model_code="7420",
        building="HQ",
        building_room="HQ/101",
        notes="Ready",
        case_number="CASE-OPTIONAL",
        slot_number="3",
        home_slot_id=522,
        slotted=True,
    )

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,equipment_type,case_identifier,slot_identifier\n"
        b"OPTIONAL-100,laptop,CASE-OPTIONAL,3\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Unchanged Exact Match: 1" in response.data
    assert b"Proposed Update: 0" in response.data
    assert b"manufacturer</code>" not in response.data
    assert b"serial_number</code>" not in response.data
    assert b"notes</code>" not in response.data


def test_existing_asset_present_blank_optional_fields_preserve_current_values(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=523, case_name="CASE-BLANKOPT", slot_position=4, current_asset_tag="BLANKOPT-100")
    _insert_asset(
        asset_tag="BLANKOPT-100",
        serial_number="SER-BLANKOPT-100",
        equipment_type="switch",
        manufacturer="Cisco",
        model="Catalyst",
        model_code="9300",
        building="HQ",
        building_room="HQ/201",
        notes="Existing note",
        case_number="CASE-BLANKOPT",
        slot_number="4",
        home_slot_id=523,
        slotted=True,
    )

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,manufacturer,model,model_code,building_room,"
        b"location_building,notes_comments,case_identifier,slot_identifier\n"
        b"BLANKOPT-100,,switch,,,,,,,CASE-BLANKOPT,4\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Unchanged Exact Match: 1" in response.data
    assert b"Proposed Update: 0" in response.data
    assert b"manufacturer</code>" not in response.data
    assert b"serial_number</code>" not in response.data
    assert b"notes</code>" not in response.data


def test_asset_import_preview_shows_proposed_update_changed_fields(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=503, case_name="CASE-UPD", slot_position=3, current_asset_tag="UPD-100")
    _insert_asset(
        asset_tag="UPD-100",
        serial_number="SER-UPD-100",
        equipment_type="router",
        manufacturer="Old Maker",
        model="Old Model",
        case_number="CASE-UPD",
        slot_number="3",
        home_slot_id=503,
        slotted=True,
    )

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,manufacturer,model,case_identifier,slot_identifier\n"
        b"UPD-100,SER-UPD-100,router,New Maker,New Model,CASE-UPD,3\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Proposed Update: 1" in response.data
    assert b"Existing asset has proposed field updates." in response.data
    assert b"manufacturer</code>: Old Maker -> New Maker" in response.data
    assert b"model</code>: Old Model -> New Model" in response.data


def test_existing_asset_different_available_slot_shows_readable_labels(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=524, case_name="CASE-OLD", slot_position=5, current_asset_tag="MOVE-100")
    _insert_slot(slot_id=525, case_name="CASE-NEW", slot_position=6)
    _insert_asset(
        asset_tag="MOVE-100",
        serial_number="SER-MOVE-100",
        equipment_type="router",
        manufacturer="Juniper",
        model="MX",
        case_number="CASE-OLD",
        slot_number="5",
        home_slot_id=524,
        slotted=True,
    )

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,manufacturer,model,case_identifier,slot_identifier\n"
        b"MOVE-100,SER-MOVE-100,router,Juniper,MX,CASE-NEW,6\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Proposed Update: 1" in response.data
    assert b"Existing asset would move to a different available home slot." in response.data
    assert b"home_slot</code>: CASE-OLD / 5 -> CASE-NEW / 6" in response.data
    assert b"home_slot_id" not in response.data


def test_asset_import_preview_classifies_unslotted_missing_storage_and_acknowledgment(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type\nUNSLOT-100,SER-UNSLOT-100,laptop\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Unslotted Import: 1" in response.data
    assert b"No storage case and slot supplied" in response.data
    assert b"Unslotted acknowledgment is required before these rows can continue." in response.data

    before = _table_counts()
    acknowledged_response = client_with_temp_db.post(
        "/admin/assets/import",
        data={
            "acknowledge_unslotted": "1",
            "asset_file": (
                io.BytesIO(b"asset_tag,serial_number,equipment_type\nUNSLOT-100,SER-UNSLOT-100,laptop\n"),
                "assets.csv",
            ),
        },
        content_type="multipart/form-data",
    )
    after = _table_counts()

    assert acknowledged_response.status_code == 200
    assert after == before
    assert b"Unslotted import acknowledged for rows with missing or unavailable storage." in acknowledged_response.data


def test_csv_and_xlsx_preview_preserve_blank_existing_fields_equivalently(
    client_with_temp_db,
    tmp_path: Path,
) -> None:
    _insert_asset(
        asset_tag="PARITY-100",
        serial_number="SER-PARITY-100",
        equipment_type="laptop",
        manufacturer="Dell",
        model="Latitude",
    )
    csv_path = tmp_path / "assets.csv"
    csv_path.write_text(
        "asset_tag,serial_number,equipment_type,manufacturer,model,case_identifier,slot_identifier\n"
        "PARITY-100,,laptop,,,,\n",
        encoding="utf-8",
    )
    xlsx_path = tmp_path / "assets.xlsx"
    xlsx_path.write_bytes(
        _xlsx_bytes(
            [
                {
                    "clean_asset_tag": "PARITY-100",
                    "serial_number": "",
                    "equipment_type": "laptop",
                    "manufacturer": "",
                    "model": "",
                    "case_identifier": "",
                    "slot_identifier": "",
                }
            ]
        )
    )

    conn = sqlite3.connect(f"file:{db.DB_PATH.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        csv_preview = build_asset_import_preview(
            conn,
            analyze_asset_import_csv(csv_path, filename="assets.csv", collect_row_errors=True),
        )
        xlsx_preview = build_asset_import_preview(
            conn,
            analyze_asset_import_xlsx(xlsx_path, filename="assets.xlsx", collect_row_errors=True),
        )
    finally:
        conn.close()

    assert [(row.category, row.changed_fields) for row in csv_preview.rows] == [
        (row.category, row.changed_fields) for row in xlsx_preview.rows
    ]
    assert csv_preview.rows[0].category == xlsx_preview.rows[0].category == "unchanged_exact_match"


def test_asset_import_preview_classifies_slot_conflict_as_unslotted_eligible(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=504, case_name="CASE-BUSY", slot_position=4, current_asset_tag="BUSY-OTHER")
    _insert_asset(asset_tag="BUSY-OTHER", home_slot_id=504, case_number="CASE-BUSY", slot_number="4", slotted=True)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,case_identifier,slot_identifier\n"
        b"BUSY-100,SER-BUSY-100,switch,CASE-BUSY,4\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Slot Conflict Eligible For Unslotted Import: 1" in response.data
    assert b"Requested slot is occupied by BUSY-OTHER" in response.data
    assert b"Existing slot occupants are never displaced." in response.data
    assert b"Unslotted acknowledgment is required before these rows can continue." in response.data


def test_asset_import_preview_classifies_identity_conflict(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_asset(asset_tag="SERIAL-OWNER", serial_number="SER-CONFLICT")

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type\nOTHER-TAG,SER-CONFLICT,laptop\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Identity Conflict: 1" in response.data
    assert b"serial_number matches existing asset SERIAL-OWNER" in response.data
    assert b"serial_number" in response.data


def test_asset_import_preview_classifies_invalid_and_duplicate_upload_rows(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type\n"
        b"DUP-100,SER-DUP-100,laptop\n"
        b",SER-MISSING,switch\n"
        b"DUP-100,SER-DUP-200,router\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Invalid Or Duplicate Upload Row: 2" in response.data
    assert b"asset_tag or barcode is required." in response.data
    assert b"duplicate asset_tag matches row 2: DUP-100." in response.data


def test_asset_import_preview_groups_rows_by_category_with_expected_disclosure_defaults(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=530, case_name="CASE-GROUP-NEW", slot_position=1)
    _insert_slot(slot_id=531, case_name="CASE-GROUP-EXACT", slot_position=2, current_asset_tag="GROUP-EXACT")
    _insert_slot(slot_id=532, case_name="CASE-GROUP-UPD", slot_position=3, current_asset_tag="GROUP-UPD")
    _insert_slot(slot_id=533, case_name="CASE-GROUP-BUSY", slot_position=4, current_asset_tag="GROUP-BUSY-OTHER")
    _insert_asset(
        asset_tag="GROUP-EXACT",
        serial_number="SER-GROUP-EXACT",
        equipment_type="switch",
        manufacturer="Cisco",
        model="Catalyst",
        case_number="CASE-GROUP-EXACT",
        slot_number="2",
        home_slot_id=531,
        slotted=True,
    )
    _insert_asset(
        asset_tag="GROUP-UPD",
        serial_number="SER-GROUP-UPD",
        equipment_type="laptop",
        manufacturer="Old Maker",
        model="Latitude",
        case_number="CASE-GROUP-UPD",
        slot_number="3",
        home_slot_id=532,
        slotted=True,
    )
    _insert_asset(
        asset_tag="GROUP-BUSY-OTHER",
        equipment_type="router",
        case_number="CASE-GROUP-BUSY",
        slot_number="4",
        home_slot_id=533,
        slotted=True,
    )
    _insert_asset(asset_tag="GROUP-SERIAL-OWNER", serial_number="SER-GROUP-CONFLICT")

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,manufacturer,model,case_identifier,slot_identifier\n"
        b"GROUP-NEW,SER-GROUP-NEW,laptop,Dell,Latitude,CASE-GROUP-NEW,1\n"
        b"GROUP-EXACT,SER-GROUP-EXACT,switch,Cisco,Catalyst,CASE-GROUP-EXACT,2\n"
        b"GROUP-UNSLOT,SER-GROUP-UNSLOT,router,Juniper,MX,,\n"
        b"GROUP-UPD,SER-GROUP-UPD,laptop,New Maker,Latitude,CASE-GROUP-UPD,3\n"
        b"GROUP-BUSY,SER-GROUP-BUSY,switch,,,CASE-GROUP-BUSY,4\n"
        b"GROUP-CONFLICT,SER-GROUP-CONFLICT,laptop,,,,\n"
        b",SER-GROUP-MISSING,router,,,,\n",
        "assets.csv",
    )

    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "New Asset: 1" in html
    assert "Unchanged Exact Match: 1" in html
    assert "Proposed Update: 1" in html
    assert "Unslotted Import: 1" in html
    assert "Slot Conflict Eligible For Unslotted Import: 1" in html
    assert "Identity Conflict: 1" in html
    assert "Invalid Or Duplicate Upload Row: 1" in html

    for section_id in (
        "asset-import-new-asset",
        "asset-import-unchanged-exact-match",
        "asset-import-unslotted-import",
    ):
        assert "open" not in _details_tag(html, section_id)

    for section_id in (
        "asset-import-proposed-update",
        "asset-import-slot-conflict-unslotted",
        "asset-import-identity-conflict",
        "asset-import-invalid-duplicate-upload-row",
    ):
        assert "open" in _details_tag(html, section_id)

    assert html.count("1 row") >= 7
    assert 'class="import-row-table-wrap"' in html
    assert "<th>Row</th>" in html
    assert "Unslotted acknowledgment is required before these rows can continue." in html

    for asset_tag in (
        "GROUP-NEW",
        "GROUP-EXACT",
        "GROUP-UNSLOT",
        "GROUP-UPD",
        "GROUP-BUSY",
        "GROUP-CONFLICT",
    ):
        assert asset_tag in html
    assert "asset_tag or barcode is required." in html


def test_traversal_style_csv_filename_uses_server_tempfile_suffix(
    client_with_temp_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_admin(client_with_temp_db)
    created_paths: list[Path] = []
    original_named_temporary_file = intake_app.tempfile.NamedTemporaryFile

    def recording_named_temporary_file(*args, **kwargs):
        assert kwargs["suffix"] == ".csv"
        handle = original_named_temporary_file(*args, **kwargs)
        created_paths.append(Path(handle.name))
        return handle

    monkeypatch.setattr(intake_app.tempfile, "NamedTemporaryFile", recording_named_temporary_file)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type\nAT-100,SN-100,laptop\n",
        "../../outside.csv",
    )

    assert response.status_code == 200
    assert b"Asset import preview complete. No database changes were made." in response.data
    assert created_paths
    temp_root = Path(tempfile.gettempdir()).resolve()
    for created_path in created_paths:
        assert created_path.parent.resolve() == temp_root
        assert created_path.suffix == ".csv"
        assert "outside" not in created_path.name
        assert not created_path.exists()


def test_traversal_style_xlsx_filename_uses_server_tempfile_suffix(
    client_with_temp_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_admin(client_with_temp_db)
    created_paths: list[Path] = []
    original_named_temporary_file = intake_app.tempfile.NamedTemporaryFile

    def recording_named_temporary_file(*args, **kwargs):
        assert kwargs["suffix"] == ".xlsx"
        handle = original_named_temporary_file(*args, **kwargs)
        created_paths.append(Path(handle.name))
        return handle

    monkeypatch.setattr(intake_app.tempfile, "NamedTemporaryFile", recording_named_temporary_file)

    response = _post_file(client_with_temp_db, _xlsx_bytes(), "..\\..\\outside.xlsx")

    assert response.status_code == 200
    assert b"Asset import preview complete. No database changes were made." in response.data
    assert created_paths
    temp_root = Path(tempfile.gettempdir()).resolve()
    for created_path in created_paths:
        assert created_path.parent.resolve() == temp_root
        assert created_path.suffix == ".xlsx"
        assert "outside" not in created_path.name
        assert not created_path.exists()


def test_unsupported_asset_import_extension_is_rejected_clearly(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(client_with_temp_db, b"asset_tag,equipment_type\nAT-100,laptop\n", "assets.txt")

    assert response.status_code == 200
    assert b"Unsupported file type. Upload a .csv or .xlsx file." in response.data


def test_malformed_csv_returns_useful_error_without_database_writes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,asset_tag,equipment_type\nAT-100,AT-101,laptop\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Malformed CSV file. Column headers must be unique." in response.data


def test_malformed_xlsx_returns_useful_error_without_database_writes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(client_with_temp_db, b"not a workbook", "inventory.xlsx")

    assert response.status_code == 200
    assert b"Malformed XLSX file. Upload a valid .xlsx workbook." in response.data


def test_missing_identity_is_rejected_without_database_writes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,barcode,clean_asset_tag,equipment_type\n,,,laptop\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"asset_tag or barcode is required." in response.data


def test_unsupported_equipment_type_is_rejected_without_database_writes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,equipment_type\nMON-100,monitor\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Supported asset types are Laptop, Switch, and Router." in response.data


def test_csv_upload_ignores_unknown_and_cmdb_style_columns_with_warning_without_database_writes(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,equipment_type,mac_address,owner\nSW-MAC,switch,00:11:22:33:44:55,Alice\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Asset import preview complete. No database changes were made." in response.data
    assert b"Preview generated successfully. No database changes were made." in response.data
    assert b"Warnings:" in response.data
    assert b"Ignored unsupported CSV columns: mac_address, owner." in response.data


def test_xlsx_upload_ignores_unknown_and_cmdb_style_columns_with_warning_without_database_writes(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "clean_asset_tag": "SW-MAC",
                    "equipment_type": "switch",
                    "mac_address": "00:11:22:33:44:55",
                    "owner": "Alice",
                }
            ]
        ).to_excel(writer, index=False)

    response = _post_file(client_with_temp_db, buffer.getvalue(), "assets.xlsx")

    assert response.status_code == 200
    assert b"Asset import preview complete. No database changes were made." in response.data
    assert b"Warnings:" in response.data
    assert b"Ignored unsupported XLSX columns: mac_address, owner." in response.data


def test_ignored_columns_do_not_enter_canonical_analysis_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "assets.csv"
    csv_path.write_text(
        "asset_tag,equipment_type,mac_address,owner\n"
        "SW-MAC,switch,00:11:22:33:44:55,Alice\n",
        encoding="utf-8",
    )

    analysis = analyze_asset_import_csv(csv_path, filename="assets.csv")

    assert analysis.warnings == ("Ignored unsupported CSV columns: mac_address, owner.",)
    assert len(analysis.rows) == 1
    row = analysis.rows[0]
    assert row.asset_tag == "SW-MAC"
    assert row.equipment_type == "switch"
    assert "mac_address" not in row.__dataclass_fields__
    assert "owner" not in row.__dataclass_fields__
    assert "00:11:22:33:44:55" not in str(row)
    assert "Alice" not in str(row)


def test_supported_optional_columns_are_mapped_to_canonical_analysis_row(tmp_path: Path) -> None:
    csv_path = tmp_path / "assets.csv"
    csv_path.write_text(
        "asset_tag,barcode,clean_asset_tag,serial_number,equipment_type,manufacturer,model,model_code,"
        "building_room,location_building,case_number,slot_number,notes_comments\n"
        ",BAR-100,CLEAN-100,SN-100,laptop,Dell,Latitude,7420,HQ/101,HQ,alpha,7,Ready\n",
        encoding="utf-8",
    )

    analysis = analyze_asset_import_csv(csv_path, filename="assets.csv")

    assert analysis.warnings == ()
    assert len(analysis.rows) == 1
    row = analysis.rows[0]
    assert row.asset_tag == "BAR-100"
    assert row.serial_number == "SN-100"
    assert row.equipment_type == "laptop"
    assert row.manufacturer == "Dell"
    assert row.model == "Latitude"
    assert row.model_code == "7420"
    assert row.building_room == "HQ/101"
    assert row.location_building == "HQ"
    assert row.case_identifier == "CASE-ALPHA"
    assert row.slot_identifier == "7"
    assert row.notes == "Ready"
    assert row.storage_intent == "slotted"


def test_direct_storage_columns_override_legacy_storage_aliases(tmp_path: Path) -> None:
    csv_path = tmp_path / "assets.csv"
    csv_path.write_text(
        "asset_tag,equipment_type,case_identifier,slot_identifier,case_number,slot_number\n"
        "SW-100,switch,CASE-DIRECT,3,legacy,8\n",
        encoding="utf-8",
    )

    row = analyze_asset_import_csv(csv_path, filename="assets.csv").rows[0]

    assert row.case_identifier == "CASE-DIRECT"
    assert row.slot_identifier == "3"


def test_slot_helper_is_ignored_with_visible_warning(tmp_path: Path) -> None:
    csv_path = tmp_path / "assets.csv"
    csv_path.write_text(
        "asset_tag,equipment_type,slot_helper\n"
        "SW-HELPER,switch,4\n",
        encoding="utf-8",
    )

    analysis = analyze_asset_import_csv(csv_path, filename="assets.csv")

    assert analysis.warnings == ("Ignored unsupported CSV column: slot_helper.",)
    assert len(analysis.rows) == 1
    row = analysis.rows[0]
    assert row.asset_tag == "SW-HELPER"
    assert row.storage_intent == "unslotted"
    assert "slot_helper" not in row.__dataclass_fields__
    assert "4" not in str(row)


def test_duplicate_asset_rows_are_rejected_without_database_writes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,barcode,equipment_type\nDUP-100,,laptop\n,dup-100,switch\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"duplicate asset_tag matches row 2: DUP-100." in response.data


def test_duplicate_serial_rows_are_rejected_without_database_writes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type\nLAP-100,SN-DUP,laptop\nSW-100,sn-dup,switch\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"duplicate serial_number matches row 2: sn-dup." in response.data


def test_operator_is_forbidden_from_asset_import_upload_page(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-asset-import", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    get_response = client_with_temp_db.get("/admin/assets/import")
    post_response = client_with_temp_db.post(
        "/admin/assets/import",
        data={"asset_file": (io.BytesIO(b"asset_tag,equipment_type\nAT-100,laptop\n"), "assets.csv")},
        content_type="multipart/form-data",
    )

    assert get_response.status_code == 403
    assert post_response.status_code == 403
