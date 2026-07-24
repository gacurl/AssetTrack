from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pandas as pd
import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.import_analysis import analyze_asset_import_csv, analyze_asset_import_xlsx
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
    assert b"Asset import analysis complete. No database changes were made." in response.data
    assert b"File analyzed successfully. No database changes were made." in response.data
    assert b"Laptop" in response.data
    assert b"Switch" in response.data
    assert b"Router" in response.data


def test_xlsx_upload_analyzes_laptop_switch_and_router_without_database_writes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(client_with_temp_db, _xlsx_bytes(), "inventory.xlsx")

    assert response.status_code == 200
    assert b"Asset import analysis complete. No database changes were made." in response.data
    assert b"XLSX" in response.data
    assert b"Laptop" in response.data
    assert b"Switch" in response.data
    assert b"Router" in response.data


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
    assert b"Asset import analysis complete. No database changes were made." in response.data
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
    assert b"Asset import analysis complete. No database changes were made." in response.data
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
    assert b"Row 2: asset_tag or barcode is required." in response.data


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
    assert b"Asset import analysis complete. No database changes were made." in response.data
    assert b"File analyzed successfully. No database changes were made." in response.data
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
    assert b"Asset import analysis complete. No database changes were made." in response.data
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
    assert b"Row 3: duplicate asset_tag matches row 2: DUP-100." in response.data


def test_duplicate_serial_rows_are_rejected_without_database_writes(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = _post_file(
        client_with_temp_db,
        b"asset_tag,serial_number,equipment_type\nLAP-100,SN-DUP,laptop\nSW-100,sn-dup,switch\n",
        "assets.csv",
    )

    assert response.status_code == 200
    assert b"Row 3: duplicate serial_number matches row 2: sn-dup." in response.data


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
