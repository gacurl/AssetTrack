from __future__ import annotations

import csv
import json

import io
import re
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd
import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.import_analysis import ALLOWED_COLUMNS, analyze_asset_import_csv, analyze_asset_import_xlsx
from assettrack.import_reconciliation import build_asset_import_preview
from tests.auth_test_utils import create_test_user, login_session


ASSET_IMPORT_TEMPLATE_HEADERS = [
    "equipment_type",
    "asset_tag",
    "barcode",
    "serial_number",
    "manufacturer",
    "model",
    "model_code",
    "building_room",
    "case_identifier",
    "slot_identifier",
    "notes_comments",
]
ASSET_IMPORT_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "docs" / "fixtures" / "imports" / "asset_import_template.csv"


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


def test_canonical_asset_import_template_headers_match_parser_contract() -> None:
    with ASSET_IMPORT_TEMPLATE_PATH.open(newline="", encoding="utf-8") as handle:
        headers = next(csv.reader(handle))

    assert headers == ASSET_IMPORT_TEMPLATE_HEADERS
    assert set(headers) <= ALLOWED_COLUMNS
    analysis = analyze_asset_import_csv(ASSET_IMPORT_TEMPLATE_PATH, filename="asset_import_template.csv")
    assert analysis.file_type == "CSV"
    assert analysis.rows == ()
    assert analysis.warnings == ()


def test_canonical_asset_import_template_supports_laptop_switch_and_router_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "assets.csv"
    csv_path.write_text(
        ",".join(ASSET_IMPORT_TEMPLATE_HEADERS)
        + "\n"
        + "Laptop,LAP-100,,SER-LAP-100,Dell,Latitude,7420,HQ 101,,,Ready for issue\n"
        + "Switch,,SW-BC-100,SER-SW-100,Cisco,Catalyst,C9300,Network Lab,,,Barcode identity\n"
        + "Router,RTR-100,,SER-RTR-100,Juniper,MX,MX204,Storage,CASE-CORE,4,Slotted intent\n",
        encoding="utf-8",
    )

    analysis = analyze_asset_import_csv(csv_path, filename="assets.csv")

    assert [row.equipment_type for row in analysis.rows] == ["laptop", "switch", "router"]
    assert [row.asset_tag for row in analysis.rows] == ["LAP-100", "SW-BC-100", "RTR-100"]
    assert analysis.rows[0].storage_intent == "unslotted"
    assert analysis.rows[1].storage_intent == "unslotted"
    assert analysis.rows[2].case_identifier == "CASE-CORE"
    assert analysis.rows[2].slot_identifier == "4"
    assert analysis.rows[2].storage_intent == "slotted"
    assert analysis.warnings == ()


def _table_counts() -> dict[str, int]:
    conn = db.get_connection()
    try:
        return {
            "assets": int(conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0]),
            "asset_events": int(conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0]),
            "slots": int(conn.execute("SELECT COUNT(*) FROM slots;").fetchone()[0]),
            "slot_occupancy": int(conn.execute("SELECT COUNT(*) FROM slot_occupancy;").fetchone()[0]),
        }
    finally:
        conn.close()


def _post_file(client, content: bytes, filename: str, *, form: dict[str, str] | None = None):
    before = _table_counts()
    data = dict(form or {})
    data["asset_file"] = (io.BytesIO(content), filename)
    response = client.post(
        "/admin/assets/import",
        data=data,
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


def test_slot_identifiers_normalize_integer_like_csv_and_xlsx_values(tmp_path: Path) -> None:
    csv_path = tmp_path / "assets.csv"
    csv_path.write_text(
        "asset_tag,equipment_type,case_identifier,slot_identifier\n"
        "CSV-INT,laptop,CASE-CSV,4\n"
        "CSV-DECIMAL,switch,CASE-CSV,4.0\n",
        encoding="utf-8",
    )
    xlsx_path = tmp_path / "assets.xlsx"
    xlsx_path.write_bytes(
        _xlsx_bytes(
            [
                {
                    "clean_asset_tag": "XLSX-FOUR",
                    "equipment_type": "laptop",
                    "case_identifier": "CASE-2912-SMOKE",
                    "slot_identifier": 4.0,
                },
                {
                    "clean_asset_tag": "XLSX-NINES",
                    "equipment_type": "router",
                    "case_identifier": "CASE-999",
                    "slot_identifier": 999.0,
                },
                {
                    "clean_asset_tag": "XLSX-FRACTION",
                    "equipment_type": "switch",
                    "case_identifier": "CASE-FRACTION",
                    "slot_identifier": 4.5,
                },
            ]
        )
    )

    csv_rows = analyze_asset_import_csv(csv_path, filename="assets.csv").rows
    xlsx_rows = analyze_asset_import_xlsx(xlsx_path, filename="assets.xlsx").rows

    assert [row.slot_identifier for row in csv_rows] == ["4", "4"]
    assert [row.slot_identifier for row in xlsx_rows] == ["4", "999", "4.5"]
    assert xlsx_rows[0].case_identifier == "CASE-2912-SMOKE"


def test_fractional_slot_identifier_is_rejected_without_rounding(
    client_with_temp_db,
    tmp_path: Path,
) -> None:
    xlsx_path = tmp_path / "assets.xlsx"
    xlsx_path.write_bytes(
        _xlsx_bytes(
            [
                {
                    "clean_asset_tag": "XLSX-FRACTION",
                    "equipment_type": "laptop",
                    "case_identifier": "CASE-FRACTION",
                    "slot_identifier": 4.5,
                }
            ]
        )
    )

    analysis = analyze_asset_import_xlsx(xlsx_path, filename="assets.xlsx", collect_row_errors=True)
    assert analysis.rows[0].slot_identifier == "4.5"

    conn = sqlite3.connect(f"file:{db.DB_PATH.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        preview = build_asset_import_preview(conn, analysis)
    finally:
        conn.close()

    assert preview.rows[0].category == "slot_conflict_unslotted"
    assert preview.rows[0].message == "slot_identifier must be numeric; row can continue as Unslotted after acknowledgment."


def test_xlsx_numeric_slot_identifier_reaches_available_slot_classification(
    client_with_temp_db,
    tmp_path: Path,
) -> None:
    _insert_slot(slot_id=560, case_name="CASE-2912-SMOKE", slot_position=4)
    xlsx_path = tmp_path / "assets.xlsx"
    xlsx_path.write_bytes(
        _xlsx_bytes(
            [
                {
                    "clean_asset_tag": "XLSX-SLOT-4",
                    "equipment_type": "laptop",
                    "case_identifier": "CASE-2912-SMOKE",
                    "slot_identifier": 4.0,
                }
            ]
        )
    )

    analysis = analyze_asset_import_xlsx(xlsx_path, filename="assets.xlsx", collect_row_errors=True)
    conn = sqlite3.connect(f"file:{db.DB_PATH.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        preview = build_asset_import_preview(conn, analysis)
    finally:
        conn.close()

    assert analysis.rows[0].case_identifier == "CASE-2912-SMOKE"
    assert analysis.rows[0].slot_identifier == "4"
    assert preview.rows[0].category == "new_asset"


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
    assert b"Ready to commit" in response.data
    assert b"Committed rows" not in response.data
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
    assert b"Blocked Rows To Fix" in response.data
    assert b"serial_number matches existing asset SERIAL-OWNER" in response.data
    assert b"Use a unique asset tag and serial number" in response.data
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
    assert b"Blocked Rows To Fix" in response.data
    assert b"<code>DUP-100</code>" in response.data
    assert b"missing asset_tag or barcode" in response.data
    assert b"asset_tag or barcode is required." in response.data
    assert b"duplicate asset_tag matches row 2: DUP-100." in response.data
    assert b"Correct the upload row, then analyze the file again." in response.data

def test_asset_import_blocked_row_uses_barcode_identifier_when_asset_tag_blank(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,barcode,equipment_type,case_identifier,slot_identifier\n,BC-BAD,laptop,CASE-ONLY,\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Blocked Rows To Fix" in response.data
    assert b"<code>BC-BAD</code>" in response.data
    assert b"missing asset_tag or barcode" not in response.data
    assert b"Correct the upload row, then analyze the file again." in response.data


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
    assert "Technical Details" in html
    assert "Blocked Rows To Fix" in html
    assert "Required correction" in html

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
        assert created_path.exists()
    assert _pending_temp_path(client_with_temp_db) == created_paths[-1]

    logout_response = client_with_temp_db.get("/logout")

    assert logout_response.status_code == 302
    for created_path in created_paths:
        assert not created_path.exists()


def test_traversal_style_xlsx_filename_uses_server_tempfile_suffix(
    client_with_temp_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_admin(client_with_temp_db)
    xlsx_content = _xlsx_bytes()
    created_paths: list[Path] = []
    original_named_temporary_file = intake_app.tempfile.NamedTemporaryFile

    def recording_named_temporary_file(*args, **kwargs):
        if kwargs.get("prefix") == "openpyxl.":
            return original_named_temporary_file(*args, **kwargs)
        assert kwargs["suffix"] == ".xlsx"
        handle = original_named_temporary_file(*args, **kwargs)
        created_paths.append(Path(handle.name))
        return handle

    monkeypatch.setattr(intake_app.tempfile, "NamedTemporaryFile", recording_named_temporary_file)

    response = _post_file(client_with_temp_db, xlsx_content, "..\\..\\outside.xlsx")

    assert response.status_code == 200
    assert b"Asset import preview complete. No database changes were made." in response.data
    assert created_paths
    temp_root = Path(tempfile.gettempdir()).resolve()
    for created_path in created_paths:
        assert created_path.parent.resolve() == temp_root
        assert created_path.suffix == ".xlsx"
        assert "outside" not in created_path.name
        assert created_path.exists()
    assert _pending_temp_path(client_with_temp_db) == created_paths[-1]

    logout_response = client_with_temp_db.get("/logout")

    assert logout_response.status_code == 302
    for created_path in created_paths:
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


def _preview_token(response) -> str:
    match = re.search(rb'name="preview_token" value="([a-f0-9]{64})"', response.data)
    assert match is not None
    return match.group(1).decode("ascii")


def _post_commit(client, token: str):
    return client.post(
        "/admin/assets/import",
        data={"action": "commit", "preview_token": token, "confirm_import": "1"},
    )




def _pending_asset_import(client) -> dict:
    with client.session_transaction() as sess:
        pending = sess.get("pending_asset_import")
        return dict(pending) if isinstance(pending, dict) else {}


def _pending_temp_path(client) -> Path:
    pending = _pending_asset_import(client)
    temp_path = str(pending.get("temp_path") or "").strip()
    assert temp_path
    return Path(temp_path)


def _asset_events(asset_tag: str) -> list[sqlite3.Row]:
    conn = db.get_connection()
    try:
        return list(
            conn.execute(
                """
                SELECT event_type, payload
                FROM asset_events
                WHERE asset_tag = ?
                ORDER BY id;
                """,
                (asset_tag,),
            ).fetchall()
        )
    finally:
        conn.close()


def _asset_record(asset_tag: str) -> sqlite3.Row | None:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT * FROM assets WHERE asset_tag = ? LIMIT 1;", (asset_tag,)).fetchone()
    finally:
        conn.close()


def _slot_record(slot_id: int) -> sqlite3.Row:
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT * FROM slots WHERE id = ?;", (slot_id,)).fetchone()
        assert row is not None
        return row
    finally:
        conn.close()


def _slot_records_for_case(case_name: str) -> list[sqlite3.Row]:
    conn = db.get_connection()
    try:
        return list(
            conn.execute(
                """
                SELECT *
                FROM slots
                WHERE UPPER(case_name) = UPPER(?)
                ORDER BY slot_position;
                """,
                (case_name,),
            ).fetchall()
        )
    finally:
        conn.close()


def _occupancy_asset_tags() -> dict[int, str]:
    conn = db.get_connection()
    try:
        return {
            int(row["slot_id"]): str(row["asset_tag"])
            for row in conn.execute(
                """
                SELECT so.slot_id, a.asset_tag
                FROM slot_occupancy so
                JOIN assets a ON a.id = so.asset_id;
                """
            ).fetchall()
        }
    finally:
        conn.close()


def test_asset_import_missing_requested_slot_previews_and_commits_created_storage(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,manufacturer,model,case_identifier,slot_identifier\n"
        b"CREATE-SLOT-100,SER-CREATE-SLOT-100,laptop,Dell,Latitude,CASE-CREATE,12\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Ready to commit" in response.data
    assert b"New Asset: 1" in response.data
    assert b"New Laptop asset with storage to create: CASE-CREATE / 12." in response.data
    assert b"Missing storage will be created during commit." in response.data

    commit_response = _post_commit(client_with_temp_db, _preview_token(response))

    assert commit_response.status_code == 200
    assert b"Asset import committed." in commit_response.data
    asset = _asset_record("CREATE-SLOT-100")
    assert asset is not None
    assert asset["case_number"] == "CASE-CREATE"
    assert asset["slot_number"] == "12"
    assert asset["home_slot_id"] is not None
    created_slot = _slot_record(int(asset["home_slot_id"]))
    assert created_slot["case_name"] == "CASE-CREATE"
    assert int(created_slot["slot_position"]) == 12
    assert created_slot["current_asset_tag"] == "CREATE-SLOT-100"
    assert _occupancy_asset_tags()[int(created_slot["id"])] == "CREATE-SLOT-100"
    assert [row["event_type"] for row in _asset_events("CREATE-SLOT-100")] == ["ASSET_CREATED", "SLOT_ASSIGN"]


def test_asset_import_creates_multiple_missing_sequential_slots_in_one_case(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,case_identifier,slot_identifier\n"
        b"SEQ-101,SER-SEQ-101,laptop,CASE-SEQ,1\n"
        b"SEQ-102,SER-SEQ-102,laptop,CASE-SEQ,2\n"
        b"SEQ-103,SER-SEQ-103,laptop,CASE-SEQ,3\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert response.data.count(b"Missing storage will be created during commit.") == 3

    commit_response = _post_commit(client_with_temp_db, _preview_token(response))

    assert commit_response.status_code == 200
    slots = _slot_records_for_case("CASE-SEQ")
    assert [int(slot["slot_position"]) for slot in slots] == [1, 2, 3]
    assert [slot["current_asset_tag"] for slot in slots] == ["SEQ-101", "SEQ-102", "SEQ-103"]
    assert set(_occupancy_asset_tags().values()) == {"SEQ-101", "SEQ-102", "SEQ-103"}
    for asset_tag in ("SEQ-101", "SEQ-102", "SEQ-103"):
        assert [row["event_type"] for row in _asset_events(asset_tag)] == ["ASSET_CREATED", "SLOT_ASSIGN"]


def test_asset_import_creates_missing_slots_alongside_existing_slots(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=951, case_name="CASE-MIXED", slot_position=1)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,case_identifier,slot_identifier\n"
        b"MIXED-EXISTING,SER-MIXED-EXISTING,laptop,CASE-MIXED,1\n"
        b"MIXED-MISSING,SER-MIXED-MISSING,laptop,CASE-MIXED,2\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"New Laptop asset with available storage." in response.data
    assert b"New Laptop asset with storage to create: CASE-MIXED / 2." in response.data

    commit_response = _post_commit(client_with_temp_db, _preview_token(response))

    assert commit_response.status_code == 200
    slots = _slot_records_for_case("CASE-MIXED")
    assert [int(slot["slot_position"]) for slot in slots] == [1, 2]
    assert slots[0]["id"] == 951
    assert [slot["current_asset_tag"] for slot in slots] == ["MIXED-EXISTING", "MIXED-MISSING"]


def test_asset_import_creates_missing_slots_for_multiple_new_cases(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,case_identifier,slot_identifier\n"
        b"MULTICASE-A,SER-MULTICASE-A,laptop,CASE-MULTI-A,1\n"
        b"MULTICASE-B,SER-MULTICASE-B,laptop,CASE-MULTI-B,1\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"CASE-MULTI-A / 1" in response.data
    assert b"CASE-MULTI-B / 1" in response.data

    commit_response = _post_commit(client_with_temp_db, _preview_token(response))

    assert commit_response.status_code == 200
    assert _slot_records_for_case("CASE-MULTI-A")[0]["current_asset_tag"] == "MULTICASE-A"
    assert _slot_records_for_case("CASE-MULTI-B")[0]["current_asset_tag"] == "MULTICASE-B"


def test_asset_import_occupied_slot_remains_protected_during_commit(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=952, case_name="CASE-OCCUPIED", slot_position=1, current_asset_tag="OCCUPANT-100")
    _insert_asset(asset_tag="OCCUPANT-100", home_slot_id=952, case_number="CASE-OCCUPIED", slot_number="1", slotted=True)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,case_identifier,slot_identifier\n"
        b"OCCUPIED-IMPORT,SER-OCCUPIED-IMPORT,laptop,CASE-OCCUPIED,1\n",
        "assets.csv",
        form={"acknowledge_unslotted": "1"},
    )

    assert response.status_code == 200
    assert b"Slot Conflict Eligible For Unslotted Import: 1" in response.data
    assert b"Existing slot occupants are never displaced." in response.data

    commit_response = _post_commit(client_with_temp_db, _preview_token(response))

    assert commit_response.status_code == 200
    imported = _asset_record("OCCUPIED-IMPORT")
    assert imported is not None
    assert imported["home_slot_id"] is None
    assert _slot_record(952)["current_asset_tag"] == "OCCUPANT-100"
    assert _occupancy_asset_tags()[952] == "OCCUPANT-100"
    assert [row["event_type"] for row in _asset_events("OCCUPIED-IMPORT")] == ["ASSET_CREATED"]


def test_repeated_asset_import_creates_no_duplicate_slots_or_occupancy(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    content = (
        b"asset_tag,serial_number,equipment_type,case_identifier,slot_identifier\n"
        b"REPEAT-SLOT-100,SER-REPEAT-SLOT-100,laptop,CASE-REPEAT,1\n"
    )
    first_response = _post_file(client_with_temp_db, content, "assets.csv")
    first_commit = _post_commit(client_with_temp_db, _preview_token(first_response))
    assert first_commit.status_code == 200
    after_first = _table_counts()

    second_response = _post_file(client_with_temp_db, content, "assets.csv")
    assert second_response.status_code == 200
    assert b"Unchanged Exact Match: 1" in second_response.data
    second_commit = _post_commit(client_with_temp_db, _preview_token(second_response))

    assert second_commit.status_code == 200
    assert _table_counts() == after_first
    assert len(_slot_records_for_case("CASE-REPEAT")) == 1
    assert list(_occupancy_asset_tags().values()).count("REPEAT-SLOT-100") == 1
    assert [row["event_type"] for row in _asset_events("REPEAT-SLOT-100")] == ["ASSET_CREATED", "SLOT_ASSIGN"]


def test_asset_import_analyze_and_preview_do_not_create_missing_storage(
    client_with_temp_db,
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "assets.csv"
    csv_path.write_text(
        "asset_tag,serial_number,equipment_type,case_identifier,slot_identifier\n"
        "PREVIEW-ONLY-100,SER-PREVIEW-ONLY-100,laptop,CASE-PREVIEW-ONLY,1\n",
        encoding="utf-8",
    )
    before_analyze = _table_counts()
    analysis = analyze_asset_import_csv(csv_path, filename="assets.csv")
    after_analyze = _table_counts()

    conn = db.get_connection()
    try:
        preview = build_asset_import_preview(conn, analysis)
    finally:
        conn.close()

    assert after_analyze == before_analyze
    assert _table_counts() == before_analyze
    assert preview.rows[0].category == "new_asset"
    assert preview.rows[0].message == "New Laptop asset with storage to create: CASE-PREVIEW-ONLY / 1."
    assert _slot_records_for_case("CASE-PREVIEW-ONLY") == []


def test_asset_import_acknowledged_blank_storage_commits_unslotted_without_slot_assignment(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,case_identifier,slot_identifier\n"
        b"BLANK-STORAGE-100,SER-BLANK-STORAGE-100,laptop,,\n",
        "assets.csv",
        form={"acknowledge_unslotted": "1"},
    )

    assert response.status_code == 200
    assert b"Unslotted Import: 1" in response.data

    commit_response = _post_commit(client_with_temp_db, _preview_token(response))

    assert commit_response.status_code == 200
    asset = _asset_record("BLANK-STORAGE-100")
    assert asset is not None
    assert asset["home_slot_id"] is None
    assert asset["case_number"] in (None, "")
    assert asset["slot_number"] in (None, "")
    assert _occupancy_asset_tags() == {}
    assert [row["event_type"] for row in _asset_events("BLANK-STORAGE-100")] == ["ASSET_CREATED"]


def test_asset_import_commit_writes_approved_safe_rows_atomically_and_leaves_blocked_rows(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=901, case_name="CASE-NEW", slot_position=1)
    _insert_slot(slot_id=902, case_name="CASE-BUSY", slot_position=2, current_asset_tag="BUSY-OTHER")
    _insert_slot(slot_id=903, case_name="CASE-EXACT", slot_position=3, current_asset_tag="EXACT-300")
    _insert_slot(slot_id=904, case_name="CASE-UPD", slot_position=4, current_asset_tag="UPD-300")
    _insert_slot(slot_id=905, case_name="CASE-MOVE-OLD", slot_position=5, current_asset_tag="MOVE-ONLY")
    _insert_slot(slot_id=906, case_name="CASE-MOVE-NEW", slot_position=6)
    _insert_slot(slot_id=907, case_name="CASE-METAMOVE-OLD", slot_position=7, current_asset_tag="MOVE-META")
    _insert_slot(slot_id=908, case_name="CASE-METAMOVE-NEW", slot_position=8)
    _insert_asset(asset_tag="BUSY-OTHER", home_slot_id=902, case_number="CASE-BUSY", slot_number="2", slotted=True)
    _insert_asset(
        asset_tag="EXACT-300",
        serial_number="SER-EXACT-300",
        equipment_type="switch",
        manufacturer="Cisco",
        model="Catalyst",
        case_number="CASE-EXACT",
        slot_number="3",
        home_slot_id=903,
        slotted=True,
    )
    _insert_asset(
        asset_tag="UPD-300",
        serial_number="SER-UPD-300",
        equipment_type="router",
        manufacturer="Old Maker",
        model="Old Model",
        case_number="CASE-UPD",
        slot_number="4",
        home_slot_id=904,
        slotted=True,
    )
    _insert_asset(
        asset_tag="MOVE-ONLY",
        serial_number="SER-MOVE-ONLY",
        equipment_type="laptop",
        manufacturer="Dell",
        model="Latitude",
        building_room="HQ/105",
        case_number="CASE-MOVE-OLD",
        slot_number="5",
        home_slot_id=905,
        slotted=True,
    )
    _insert_asset(
        asset_tag="MOVE-META",
        serial_number="SER-MOVE-META",
        equipment_type="laptop",
        manufacturer="Old Maker",
        model="Latitude",
        building_room="HQ/107",
        case_number="CASE-METAMOVE-OLD",
        slot_number="7",
        home_slot_id=907,
        slotted=True,
    )
    _insert_asset(asset_tag="SERIAL-OWNER", serial_number="SER-CONFLICT")

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,manufacturer,model,case_identifier,slot_identifier\n"
        b"NEW-SLOT,SER-NEW-SLOT,laptop,Dell,Latitude,CASE-NEW,1\n"
        b"NEW-UNSLOT,SER-NEW-UNSLOT,router,Juniper,MX,,\n"
        b"BUSY-NEW,SER-BUSY-NEW,switch,Cisco,Catalyst,CASE-BUSY,2\n"
        b"EXACT-300,SER-EXACT-300,switch,Cisco,Catalyst,CASE-EXACT,3\n"
        b"UPD-300,SER-UPD-300,router,New Maker,New Model,CASE-UPD,4\n"
        b"MOVE-ONLY,SER-MOVE-ONLY,laptop,Dell,Latitude,CASE-MOVE-NEW,6\n"
        b"MOVE-META,SER-MOVE-META,laptop,New Maker,Latitude,CASE-METAMOVE-NEW,8\n"
        b"CONFLICT-TAG,SER-CONFLICT,laptop,Dell,Latitude,,\n"
        b",SER-MISSING,laptop,Dell,Latitude,,\n",
        "assets.csv",
        form={"acknowledge_unslotted": "1"},
    )
    assert response.status_code == 200
    token = _preview_token(response)

    pending_path = _pending_temp_path(client_with_temp_db)
    assert pending_path.exists()
    csv_response = client_with_temp_db.get("/admin/assets/import/reconciliation.csv")
    assert csv_response.status_code == 200
    assert csv_response.headers["Content-Type"].startswith("text/csv")
    assert b"row_number,asset_tag,category,message" in csv_response.data
    assert b"CONFLICT-TAG" in csv_response.data

    commit_response = _post_commit(client_with_temp_db, token)

    assert commit_response.status_code == 200
    assert b"Asset import committed." in commit_response.data
    assert b"Committed rows" in commit_response.data
    assert b"Blocked rows" in commit_response.data
    assert b"6 rows committed. 2 blocked rows left unchanged." in commit_response.data
    assert b"Committed rows: 6" in commit_response.data
    assert b"Blocked rows: 2" in commit_response.data
    assert b"Blocked Rows To Fix" in commit_response.data
    assert b"Required correction" in commit_response.data
    assert _asset_record("CONFLICT-TAG") is None
    assert _asset_record("SER-MISSING") is None

    assert [row["event_type"] for row in _asset_events("NEW-SLOT")] == ["ASSET_CREATED", "SLOT_ASSIGN"]
    assert [row["event_type"] for row in _asset_events("NEW-UNSLOT")] == ["ASSET_CREATED"]
    assert [row["event_type"] for row in _asset_events("BUSY-NEW")] == ["ASSET_CREATED"]
    assert _asset_record("BUSY-NEW")["home_slot_id"] is None
    assert _slot_record(902)["current_asset_tag"] == "BUSY-OTHER"

    assert _asset_events("EXACT-300") == []
    assert [row["event_type"] for row in _asset_events("UPD-300")] == ["ASSET_UPDATED"]
    assert _asset_record("UPD-300")["manufacturer"] == "New Maker"
    assert _asset_record("UPD-300")["model"] == "New Model"

    move_only_events = _asset_events("MOVE-ONLY")
    assert [row["event_type"] for row in move_only_events] == ["SLOT_MOVE"]
    move_payload = json.loads(move_only_events[0]["payload"])
    assert move_payload["from_slot"]["slot_id"] == 905
    assert move_payload["to_slot"]["slot_id"] == 906

    move_meta_events = _asset_events("MOVE-META")
    assert [row["event_type"] for row in move_meta_events] == ["SLOT_MOVE", "ASSET_UPDATED"]
    assert _asset_record("MOVE-META")["manufacturer"] == "New Maker"
    assert _occupancy_asset_tags()[901] == "NEW-SLOT"
    assert _occupancy_asset_tags()[906] == "MOVE-ONLY"
    assert _occupancy_asset_tags()[908] == "MOVE-META"
    assert not pending_path.exists()
    assert _pending_asset_import(client_with_temp_db) == {}




def test_asset_import_commit_rejected_without_confirmation_removes_pending_file_and_state(
    client_with_temp_db,
) -> None:
    _login_admin(client_with_temp_db)
    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type\nNO-CONFIRM,SER-NO-CONFIRM,laptop\n",
        "no-confirm.csv",
    )
    assert response.status_code == 200
    token = _preview_token(response)
    pending_path = _pending_temp_path(client_with_temp_db)
    assert pending_path.exists()

    commit_response = client_with_temp_db.post(
        "/admin/assets/import",
        data={"action": "commit", "preview_token": token},
    )

    assert commit_response.status_code == 200
    assert b"Confirm the preview" in commit_response.data
    assert not pending_path.exists()
    assert _pending_asset_import(client_with_temp_db) == {}
    assert _asset_record("NO-CONFIRM") is None


def test_asset_import_commit_rejects_tampered_confirmation_before_writes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=921, case_name="CASE-TAMPER", slot_position=1)
    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,case_identifier,slot_identifier\n"
        b"TAMPER-100,SER-TAMPER-100,laptop,CASE-TAMPER,1\n",
        "assets.csv",
    )

    pending_path = _pending_temp_path(client_with_temp_db)
    assert pending_path.exists()

    commit_response = _post_commit(client_with_temp_db, "0" * 64)

    assert commit_response.status_code == 200
    assert b"stale or tampered" in commit_response.data
    assert not pending_path.exists()
    assert _pending_asset_import(client_with_temp_db) == {}
    assert _asset_record("TAMPER-100") is None
    assert _asset_events("TAMPER-100") == []


def test_asset_import_commit_rejects_stale_preview_before_writes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    _insert_slot(slot_id=931, case_name="CASE-STALE", slot_position=1)
    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,case_identifier,slot_identifier\n"
        b"STALE-100,SER-STALE-100,laptop,CASE-STALE,1\n",
        "assets.csv",
    )
    token = _preview_token(response)
    pending_path = _pending_temp_path(client_with_temp_db)
    assert pending_path.exists()
    _insert_asset(asset_tag="STALE-OCCUPANT", home_slot_id=931, case_number="CASE-STALE", slot_number="1", slotted=True)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE slots SET current_asset_tag = ? WHERE id = ?;", ("STALE-OCCUPANT", 931))
        conn.commit()
    finally:
        conn.close()



    commit_response = _post_commit(client_with_temp_db, token)

    assert commit_response.status_code == 200
    assert b"preview is stale" in commit_response.data.lower()
    assert not pending_path.exists()
    assert _pending_asset_import(client_with_temp_db) == {}
    assert _asset_record("STALE-100") is None
    assert _asset_events("STALE-100") == []


def test_asset_import_commit_rolls_back_complete_batch_on_mid_batch_failure(
    client_with_temp_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_admin(client_with_temp_db)
    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type,case_identifier,slot_identifier\n"
        b"ROLL-OK,SER-ROLL-OK,laptop,CASE-ROLL,1\n"
        b"ROLL-FAIL,SER-ROLL-FAIL,laptop,CASE-ROLL,2\n",
        "assets.csv",
    )
    token = _preview_token(response)
    original_append_event = intake_app._asset_import_append_event

    def fail_second_created(*args, **kwargs):
        if kwargs.get("asset_tag") == "ROLL-FAIL" and kwargs.get("event_type") == "ASSET_CREATED":
            raise RuntimeError("forced import failure")
        return original_append_event(*args, **kwargs)

    monkeypatch.setattr(intake_app, "_asset_import_append_event", fail_second_created)

    with pytest.raises(RuntimeError, match="forced import failure"):
        _post_commit(client_with_temp_db, token)

    assert _asset_record("ROLL-OK") is None
    assert _asset_record("ROLL-FAIL") is None
    assert _asset_events("ROLL-OK") == []
    assert _asset_events("ROLL-FAIL") == []
    assert _occupancy_asset_tags() == {}
    assert _slot_records_for_case("CASE-ROLL") == []


def test_asset_import_replacing_preview_removes_previous_pending_file(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    first = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type\nREPLACE-ONE,SER-REPLACE-ONE,laptop\n",
        "first.csv",
    )
    assert first.status_code == 200
    first_path = _pending_temp_path(client_with_temp_db)
    assert first_path.exists()

    second = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type\nREPLACE-TWO,SER-REPLACE-TWO,laptop\n",
        "second.csv",
    )

    assert second.status_code == 200
    second_path = _pending_temp_path(client_with_temp_db)
    assert second_path.exists()
    assert second_path != first_path
    assert not first_path.exists()


def test_asset_import_logout_removes_pending_file_and_session_state(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type\nLOGOUT-100,SER-LOGOUT-100,laptop\n",
        "logout.csv",
    )
    assert response.status_code == 200
    pending_path = _pending_temp_path(client_with_temp_db)
    assert pending_path.exists()

    logout_response = client_with_temp_db.get("/logout")

    assert logout_response.status_code == 302
    assert not pending_path.exists()
    with client_with_temp_db.session_transaction() as sess:
        assert "pending_asset_import" not in sess
        assert "user_id" not in sess


def test_asset_import_logout_cleanup_tolerates_missing_pending_file(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)
    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type\nMISSING-100,SER-MISSING-100,laptop\n",
        "missing.csv",
    )
    assert response.status_code == 200
    pending_path = _pending_temp_path(client_with_temp_db)
    pending_path.unlink(missing_ok=True)

    logout_response = client_with_temp_db.get("/logout")

    assert logout_response.status_code == 302
    with client_with_temp_db.session_transaction() as sess:
        assert "pending_asset_import" not in sess
        assert "user_id" not in sess
