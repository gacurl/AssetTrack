from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pandas as pd
import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from scripts import import_inventory
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


def _xlsx_bytes() -> bytes:
    rows = [
        {
            "clean_asset_tag": "LAP-100",
            "case_number": "LAPTOP",
            "slot_helper": 1,
            "serial_number": "SN-LAP-100",
            "equipment_type": "laptop",
            "manufacturer": "",
            "model": "Latitude",
            "model_code": "7420",
            "building_room": "",
            "slot_number": "1",
            "mac_address": "",
        },
        {
            "clean_asset_tag": "SW-100",
            "case_number": "SWITCH",
            "slot_helper": 1,
            "serial_number": "SN-SW-100",
            "equipment_type": "switch",
            "manufacturer": "Cisco",
            "model": "Catalyst",
            "model_code": "9300",
            "building_room": "",
            "slot_number": "1",
            "mac_address": "",
        },
        {
            "clean_asset_tag": "RTR-100",
            "case_number": "ROUTER",
            "slot_helper": 1,
            "serial_number": "SN-RTR-100",
            "equipment_type": "router",
            "manufacturer": "Juniper",
            "model": "MX",
            "model_code": "204",
            "building_room": "",
            "slot_number": "1",
            "mac_address": "",
        },
    ]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(rows, columns=sorted(import_inventory.REQUIRED_COLUMNS)).to_excel(
            writer,
            sheet_name=import_inventory.SHEET_NAME,
            index=False,
        )
    return buffer.getvalue()


def test_admin_can_open_asset_import_upload_page(client_with_temp_db) -> None:
    _login_admin(client_with_temp_db)

    response = client_with_temp_db.get("/admin/assets/import")

    assert response.status_code == 200
    assert b"Admin: Import Assets" in response.data
    assert b"Analyze Import" in response.data
    assert b".csv" in response.data
    assert b".xlsx" in response.data
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
