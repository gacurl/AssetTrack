from __future__ import annotations

import io
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session

from scripts.reconcile_government_inventory import (
    active_discrepancies,
    _open_readonly_database,
    format_reconciliation,
    load_government_records,
    reconcile_inventory,
)


HEADERS = [
    "building_room",
    "case_number",
    "slot_number",
    "equipment_type",
    "asset_tag",
    "clean_asset_tag",
    "serial_number",
    "mac_address",
    "manufacturer",
    "model",
    "model_code",
]


def _create_asset_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL,
                serial_number TEXT NULL,
                location_type TEXT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE asset_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL,
                event_type TEXT NOT NULL
            );
            """
        )
        for asset_tag, serial_number, location_type in [
            ("DDC4CY0001", "SER-HYPHEN", "STORAGE"),
            ("EXACT-100", "SER-EXACT", "STORAGE"),
            ("ONLY-ACTIVE", "SER-ONLY", "IN_CUSTODY"),
            ("CONFLICT-100", "SER-DB", "STORAGE"),
            ("DUPSER-1", "SER-DUP", "STORAGE"),
            ("DUPSER-2", "SER-DUP", "STORAGE"),
            ("DUPMAC-1", "SER-MAC-1", "STORAGE"),
            ("DUPMAC-2", "SER-MAC-2", "STORAGE"),
            ("DUPTAG-1", "SER-DUPTAG-A", "STORAGE"),
            ("DUPTAG1", "SER-DUPTAG-B", "STORAGE"),
            ("TERM-RET", "SER-RET", "RETIRED"),
            ("TERM-DISP", "SER-DISP", "DISPOSED"),
        ]:
            conn.execute(
                "INSERT INTO assets (asset_tag, serial_number, location_type) VALUES (?, ?, ?);",
                (asset_tag, serial_number, location_type),
            )
        conn.execute(
            "INSERT INTO asset_events (asset_tag, event_type) VALUES (?, ?);",
            ("ONLY-ACTIVE", "created"),
        )
        conn.commit()
    finally:
        conn.close()


def _write_inventory(path: Path) -> None:
    rows = [
        ["283", "1", "1-1", "Laptop", "DDC4CY-0001", "DDC4CY0001", "SER-HYPHEN", "MAC-HYPHEN", "Dell", "Precision", ""],
        ["283", "1", "1-2", "Laptop", "EXACT-100", "", "SER-EXACT", "MAC-EXACT", "Dell", "Precision", ""],
        ["283", "1", "1-3", "Laptop", "GOV-ONLY", "", "SER-GOV-ONLY", "MAC-GOV-ONLY", "Dell", "Precision", ""],
        ["283", "1", "1-4", "Laptop", "CONFLICT-100", "", "SER-GOV", "MAC-CONFLICT", "Dell", "Precision", ""],
        ["283", "1", "1-5", "Laptop", "DUPSER-1", "", "SER-DUP", "MAC-SER-1", "Dell", "Precision", ""],
        ["283", "1", "1-6", "Laptop", "DUPSER-2", "", "SER-DUP", "MAC-SER-2", "Dell", "Precision", ""],
        ["283", "1", "1-7", "Laptop", "DUPMAC-1", "", "SER-MAC-1", "MAC-DUP", "Dell", "Precision", ""],
        ["283", "1", "1-8", "Laptop", "DUPMAC-2", "", "SER-MAC-2", "mac-dup", "Dell", "Precision", ""],
        ["283", "1", "1-9", "Laptop", "DUPTAG-1", "", "SER-DUPTAG-GOV", "MAC-DUPTAG", "Dell", "Precision", ""],
        ["283", "1", "1-10", "Laptop", "GOV-DUP", "", "SER-GOV-DUP-1", "MAC-GOV-DUP-1", "Dell", "Precision", ""],
        ["283", "1", "1-11", "Laptop", "GOVDUP", "", "SER-GOV-DUP-2", "MAC-GOV-DUP-2", "Dell", "Precision", ""],
        ["283", "1", "1-12", "Laptop", "TERM-RET", "", "SER-RET", "MAC-RET", "Dell", "Precision", ""],
    ]
    pd.DataFrame(rows, columns=HEADERS).to_csv(path, index=False)


def _counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            "assets": int(conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0]),
            "asset_events": int(conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0]),
        }
    finally:
        conn.close()


def test_government_inventory_reconciliation_is_readonly_and_deterministic(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    inventory_path = tmp_path / "government.csv"
    _create_asset_db(db_path)
    _write_inventory(inventory_path)
    before_counts = _counts(db_path)

    conn = _open_readonly_database(db_path)
    try:
        result = reconcile_inventory(conn, inventory_path)
    finally:
        conn.close()

    assert _counts(db_path) == before_counts
    assert result.summary_counts() == {
        "government_records": 12,
        "assettrack_active_records_considered": 10,
        "exact_or_normalized_tag_matches": 6,
        "government_only_assets": 1,
        "assettrack_only_active_assets": 1,
        "identity_conflicts": 1,
        "ambiguous_normalized_tags": 2,
        "duplicate_serial_warnings": 1,
        "duplicate_mac_warnings": 1,
        "retired_disposed_assettrack_records": 2,
        "retired_disposed_tag_matches": 1,
        "retired_disposed_assettrack_only": 1,
    }

    assert [(gov.asset_tag, asset.asset_tag) for gov, asset in result.tag_matches] == [
        ("DDC4CY-0001", "DDC4CY0001"),
        ("DUPMAC-1", "DUPMAC-1"),
        ("DUPMAC-2", "DUPMAC-2"),
        ("DUPSER-1", "DUPSER-1"),
        ("DUPSER-2", "DUPSER-2"),
        ("EXACT-100", "EXACT-100"),
    ]
    assert [record.asset_tag for record in result.government_only] == ["GOV-ONLY"]
    assert [record.asset_tag for record in result.assettrack_only_active] == ["ONLY-ACTIVE"]
    assert [(gov.asset_tag, asset.asset_tag) for gov, asset in result.identity_conflicts] == [("CONFLICT-100", "CONFLICT-100")]
    assert [(key, [record.asset_tag for record in records]) for key, records in result.ambiguous_government_tags] == [
        ("GOVDUP", ["GOV-DUP", "GOVDUP"])
    ]
    assert [(key, [record.asset_tag for record in records]) for key, records in result.ambiguous_assettrack_tags] == [
        ("DUPTAG1", ["DUPTAG-1", "DUPTAG1"])
    ]
    assert [(key, [record.asset_tag for record in records]) for key, records in result.duplicate_serial_warnings] == [
        ("SER-DUP", ["DUPSER-1", "DUPSER-2"])
    ]
    assert [(key, [record.asset_tag for record in records]) for key, records in result.duplicate_mac_warnings] == [
        ("MAC-DUP", ["DUPMAC-1", "DUPMAC-2"])
    ]
    assert [(gov.asset_tag, asset.asset_tag, asset.location_type) for gov, asset in result.terminal_matches] == [
        ("TERM-RET", "TERM-RET", "RETIRED")
    ]
    assert [(record.asset_tag, record.location_type) for record in result.terminal_assettrack_only] == [
        ("TERM-DISP", "DISPOSED")
    ]

    rendered = format_reconciliation(result)
    assert rendered == format_reconciliation(result)
    assert "government_records: 12" in rendered
    assert "DDC4CY-0001 -> DDC4CY0001" in rendered
    assert "CONFLICT-100 -> CONFLICT-100; serial SER-GOV != SER-DB" in rendered


def test_government_inventory_loader_supports_xlsx(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "government.xlsx"
    pd.DataFrame(
        [["Laptop", "XLSX-100", "XLSX100", "SER-XLSX-100", "MAC-XLSX-100"]],
        columns=["equipment_type", "asset_tag", "clean_asset_tag", "serial_number", "mac_address"],
    ).to_excel(xlsx_path, index=False)

    records = load_government_records(xlsx_path)

    assert len(records) == 1
    assert records[0].asset_tag == "XLSX-100"
    assert records[0].compare_tag == "XLSX100"
    assert records[0].key == "XLSX100"

def test_reconciliation_cli_supports_direct_and_module_execution(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    inventory_path = tmp_path / "government.csv"
    _create_asset_db(db_path)
    _write_inventory(inventory_path)
    repo_root = Path(__file__).resolve().parents[1]

    direct = subprocess.run(
        [
            sys.executable,
            "scripts/reconcile_government_inventory.py",
            str(inventory_path),
            "--db",
            str(db_path),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    module = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.reconcile_government_inventory",
            str(inventory_path),
            "--db",
            str(db_path),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert direct.returncode == 0, direct.stderr
    assert module.returncode == 0, module.stderr
    assert "government_records: 12" in direct.stdout
    assert direct.stdout == module.stdout

@pytest.fixture
def client_with_temp_app_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.close()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def _login_role(client, *, username: str, role: str) -> None:
    user_id = create_test_user(username=username, password="test-pass", role=role)
    login_session(client, user_id)


def _insert_app_asset(asset_tag: str, serial_number: str, location_type: str = "STORAGE") -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO assets (asset_tag, serial_number, location_type) VALUES (?, ?, ?);",
            (asset_tag, serial_number, location_type),
        )
        conn.commit()
    finally:
        conn.close()


def _app_counts() -> dict[str, int]:
    conn = db.get_connection()
    try:
        return {
            "assets": int(conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0]),
            "asset_events": int(conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0]),
            "slots": int(conn.execute("SELECT COUNT(*) FROM slots;").fetchone()[0]),
        }
    finally:
        conn.close()


def _disposition_rows() -> list[sqlite3.Row]:
    conn = db.get_connection()
    try:
        return conn.execute(
            """
            SELECT *
            FROM inventory_reconciliation_disposition_events
            ORDER BY id ASC;
            """
        ).fetchall()
    finally:
        conn.close()


def _inventory_bytes(rows: list[list[str]], *, xlsx: bool = False) -> bytes:
    frame = pd.DataFrame(rows, columns=["equipment_type", "asset_tag", "clean_asset_tag", "serial_number", "mac_address"])
    if not xlsx:
        return frame.to_csv(index=False).encode("utf-8")
    output = io.BytesIO()
    frame.to_excel(output, index=False)
    return output.getvalue()


def _post_inventory(client, content: bytes, filename: str):
    return client.post(
        "/report/inventory-reconciliation",
        data={"inventory_file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


def _active_app_discrepancy(rows: list[list[str]]):
    content = _inventory_bytes(rows)
    inventory_path = db.DB_PATH.parent / "disposition-source.csv"
    inventory_path.write_bytes(content)
    conn = db.get_connection()
    try:
        result = reconcile_inventory(conn, inventory_path)
        discrepancies = active_discrepancies(result)
    finally:
        conn.close()
        inventory_path.unlink(missing_ok=True)
    assert discrepancies
    return discrepancies[0], content


def _post_disposition(client, discrepancy, *, note: str, reviewed: bool = True):
    data = {
        "action": "save_disposition",
        "discrepancy_key": discrepancy.key,
        "discrepancy_snapshot_json": discrepancy.snapshot_json,
        "disposition_note": note,
    }
    if reviewed:
        data["is_reviewed"] = "1"
    return client.post("/report/inventory-reconciliation", data=data)


def test_inventory_reconciliation_disposition_schema_is_idempotent_and_append_only(tmp_path: Path) -> None:
    db_path = tmp_path / "assettrack.db"
    db.initialize_schema(db_path)
    db.initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    try:
        table = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'inventory_reconciliation_disposition_events';
            """
        ).fetchone()
        index = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_inventory_reconciliation_disposition_events_discrepancy_key';
            """
        ).fetchone()
        triggers = {
            str(row[0])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'trigger'
                  AND tbl_name = 'inventory_reconciliation_disposition_events';
                """
            ).fetchall()
        }
        assert table is not None
        assert index is not None
        assert triggers == {
            "inventory_reconciliation_disposition_events_no_update",
            "inventory_reconciliation_disposition_events_no_delete",
        }

        conn.execute(
            """
            INSERT INTO inventory_reconciliation_disposition_events (
                created_at,
                actor_user_id,
                actor_username,
                discrepancy_key,
                discrepancy_category,
                normalized_asset_key,
                discrepancy_snapshot_json,
                disposition_note,
                is_reviewed
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                "2026-08-13T00:00:00+00:00",
                1,
                "schema-tester",
                "key-1",
                "government_only_asset",
                "GOV1",
                '{"category":"government_only_asset"}',
                "Reviewed against source document.",
                1,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE inventory_reconciliation_disposition_events SET disposition_note = 'changed' WHERE id = 1;"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM inventory_reconciliation_disposition_events WHERE id = 1;")
    finally:
        conn.close()


def test_inventory_reconciliation_page_access_and_role_boundary(client_with_temp_app_db) -> None:
    anonymous = client_with_temp_app_db.get("/report/inventory-reconciliation")
    assert anonymous.status_code == 403

    _login_role(client_with_temp_app_db, username="operator-recon-page", role="operator")
    operator_response = client_with_temp_app_db.get("/report/inventory-reconciliation")
    assert operator_response.status_code == 200
    assert b"Analyze Government Inventory" in operator_response.data

    report_response = client_with_temp_app_db.get("/report")
    assert b'href="/report/inventory-reconciliation"' in report_response.data

    _login_role(client_with_temp_app_db, username="admin-recon-page", role="admin")
    admin_response = client_with_temp_app_db.get("/report/inventory-reconciliation")
    assert admin_response.status_code == 200


def test_inventory_reconciliation_gui_clean_csv_uses_arbitrary_filename_and_no_mutation(client_with_temp_app_db) -> None:
    _login_role(client_with_temp_app_db, username="operator-recon-clean", role="operator")
    _insert_app_asset("CLEAN100", "SER-CLEAN")
    before = _app_counts()

    response = _post_inventory(
        client_with_temp_app_db,
        _inventory_bytes([["Laptop", "CLEAN-100", "CLEAN100", "SER-CLEAN", "MAC-CLEAN"]]),
        "operator selected clean source.csv",
    )

    assert response.status_code == 200
    assert _app_counts() == before
    assert b"operator selected clean source.csv" in response.data
    assert b"CLEAN RECONCILIATION" in response.data
    assert b"<strong>1</strong><span>Government assets" in response.data
    assert b"<strong>1</strong><span>AssetTrack active assets" in response.data
    assert b"<strong>1</strong><span>Matched" in response.data
    assert b"<strong>0</strong><span>Discrepancies" in response.data


def test_inventory_reconciliation_gui_supports_arbitrary_xlsx_filename(client_with_temp_app_db) -> None:
    _login_role(client_with_temp_app_db, username="operator-recon-xlsx", role="operator")
    _insert_app_asset("XLSX100", "SER-XLSX")

    response = _post_inventory(
        client_with_temp_app_db,
        _inventory_bytes([["Laptop", "XLSX-100", "XLSX100", "SER-XLSX", "MAC-XLSX"]], xlsx=True),
        "field inventory arbitrary name.xlsx",
    )

    assert response.status_code == 200
    assert b"field inventory arbitrary name.xlsx" in response.data
    assert b"CLEAN RECONCILIATION" in response.data


def test_inventory_reconciliation_gui_rejects_unsupported_file(client_with_temp_app_db) -> None:
    _login_role(client_with_temp_app_db, username="operator-recon-reject", role="operator")

    response = _post_inventory(client_with_temp_app_db, b"not an inventory", "inventory.txt")

    assert response.status_code == 400
    assert b"Unsupported file type. Upload a .csv or .xlsx file." in response.data


def test_inventory_reconciliation_gui_discrepancy_counts_match_engine_and_no_mutation(client_with_temp_app_db, tmp_path: Path) -> None:
    _login_role(client_with_temp_app_db, username="operator-recon-discrepancy", role="operator")
    _insert_app_asset("MATCH100", "SER-MATCH")
    _insert_app_asset("ONLY-ACTIVE-GUI", "SER-ONLY")
    _insert_app_asset("CONFLICT-GUI", "SER-DB")
    _insert_app_asset("DUPTAG-GUI", "SER-DUPTAG-A")
    _insert_app_asset("DUPTAGGUI", "SER-DUPTAG-B")
    _insert_app_asset("TERM-GUI", "SER-TERM", "RETIRED")
    before = _app_counts()
    rows = [
        ["Laptop", "MATCH-100", "MATCH100", "SER-MATCH", "MAC-MATCH"],
        ["Laptop", "GOV-ONLY-GUI", "", "SER-GOV", "MAC-GOV"],
        ["Laptop", "CONFLICT-GUI", "", "SER-GOV-CONFLICT", "MAC-CONFLICT"],
        ["Laptop", "DUPTAG-GUI", "", "SER-DUPTAG-GOV", "MAC-DUPTAG"],
        ["Laptop", "DUPSER-GUI-1", "", "SER-DUP-GUI", "MAC-SER-1"],
        ["Laptop", "DUPSER-GUI-2", "", "SER-DUP-GUI", "MAC-SER-2"],
        ["Laptop", "DUPMAC-GUI-1", "", "SER-MAC-1", "MAC-DUP-GUI"],
        ["Laptop", "DUPMAC-GUI-2", "", "SER-MAC-2", "mac-dup-gui"],
        ["Laptop", "GOV-DUP-GUI", "", "SER-GOV-DUP-1", "MAC-GOV-DUP-1"],
        ["Laptop", "GOVDUPGUI", "", "SER-GOV-DUP-2", "MAC-GOV-DUP-2"],
        ["Laptop", "TERM-GUI", "", "SER-TERM", "MAC-TERM"],
    ]
    content = _inventory_bytes(rows)
    inventory_path = tmp_path / "same-engine-source.csv"
    inventory_path.write_bytes(content)

    conn = sqlite3.connect(f"file:{db.DB_PATH.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        engine_counts = reconcile_inventory(conn, inventory_path).summary_counts()
    finally:
        conn.close()

    response = _post_inventory(client_with_temp_app_db, content, "operator discrepancy source.csv")

    assert response.status_code == 200
    assert _app_counts() == before
    assert b"Inventory discrepancies found." in response.data
    assert f"Government-only: {engine_counts['government_only_assets']}".encode() in response.data
    assert f"AssetTrack-only active: {engine_counts['assettrack_only_active_assets']}".encode() in response.data
    assert f"Identity conflicts: {engine_counts['identity_conflicts']}".encode() in response.data
    assert f"Ambiguous normalized tags: {engine_counts['ambiguous_normalized_tags']}".encode() in response.data
    assert f"Duplicate serial warnings: {engine_counts['duplicate_serial_warnings']}".encode() in response.data
    assert f"Duplicate MAC warnings: {engine_counts['duplicate_mac_warnings']}".encode() in response.data
    assert f"Retired/disposed tag matches: {engine_counts['retired_disposed_tag_matches']}".encode() in response.data
    assert b"GOV-ONLY-GUI" in response.data
    assert b"ONLY-ACTIVE-GUI" in response.data
    assert b"CONFLICT-GUI" in response.data
    assert b"RECONCILIATION REQUIRES ATTENTION" in response.data


def test_inventory_reconciliation_disposition_requires_note(client_with_temp_app_db) -> None:
    _login_role(client_with_temp_app_db, username="operator-recon-note-required", role="operator")
    _insert_app_asset("MATCH-NOTE", "SER-MATCH")
    discrepancy, _content = _active_app_discrepancy(
        [
            ["Laptop", "MATCH-NOTE", "", "SER-MATCH", "MAC-MATCH"],
            ["Laptop", "GOV-NOTE-ONLY", "", "SER-GOV", "MAC-GOV"],
        ]
    )
    before = _app_counts()

    response = _post_disposition(client_with_temp_app_db, discrepancy, note="", reviewed=True)

    assert response.status_code == 400
    assert b"Enter a disposition note before saving Reviewed / Dispositioned." in response.data
    assert _disposition_rows() == []
    assert _app_counts() == before


def test_inventory_reconciliation_disposition_appends_user_and_reviewed_state(client_with_temp_app_db) -> None:
    _login_role(client_with_temp_app_db, username="operator-recon-disposition", role="operator")
    _insert_app_asset("MATCH-DISP", "SER-MATCH")
    discrepancy, _content = _active_app_discrepancy(
        [
            ["Laptop", "MATCH-DISP", "", "SER-MATCH", "MAC-MATCH"],
            ["Laptop", "GOV-DISP-ONLY", "", "SER-GOV", "MAC-GOV"],
        ]
    )
    before = _app_counts()

    first = _post_disposition(client_with_temp_app_db, discrepancy, note="Verified as accounted for.", reviewed=True)
    second = _post_disposition(client_with_temp_app_db, discrepancy, note="Supervisor confirmed.", reviewed=True)

    assert first.status_code == 302
    assert second.status_code == 302
    assert _app_counts() == before
    rows = _disposition_rows()
    assert len(rows) == 2
    assert rows[0]["discrepancy_key"] == discrepancy.key
    assert rows[0]["discrepancy_category"] == discrepancy.category
    assert rows[0]["normalized_asset_key"] == discrepancy.normalized_asset_key
    assert rows[0]["disposition_note"] == "Verified as accounted for."
    assert int(rows[0]["is_reviewed"]) == 1
    assert int(rows[0]["actor_user_id"]) > 0
    assert rows[0]["actor_username"] == "operator-recon-disposition"
    assert rows[1]["disposition_note"] == "Supervisor confirmed."
    assert int(rows[1]["id"]) > int(rows[0]["id"])


def test_inventory_reconciliation_disposition_persists_explicit_unreviewed_state(client_with_temp_app_db) -> None:
    _login_role(client_with_temp_app_db, username="operator-recon-unreviewed", role="operator")
    _insert_app_asset("MATCH-UNREVIEWED", "SER-MATCH")
    discrepancy, _content = _active_app_discrepancy(
        [
            ["Laptop", "MATCH-UNREVIEWED", "", "SER-MATCH", "MAC-MATCH"],
            ["Laptop", "GOV-UNREVIEWED-ONLY", "", "SER-GOV", "MAC-GOV"],
        ]
    )

    response = _post_disposition(client_with_temp_app_db, discrepancy, note="Research note only.", reviewed=False)

    assert response.status_code == 302
    rows = _disposition_rows()
    assert len(rows) == 1
    assert rows[0]["disposition_note"] == "Research note only."
    assert int(rows[0]["is_reviewed"]) == 0


def test_inventory_reconciliation_unchanged_discrepancy_reassociates_and_complete_state(client_with_temp_app_db) -> None:
    _login_role(client_with_temp_app_db, username="operator-recon-complete", role="operator")
    _insert_app_asset("MATCH-COMPLETE", "SER-MATCH")
    rows = [
        ["Laptop", "MATCH-COMPLETE", "", "SER-MATCH", "MAC-MATCH"],
        ["Laptop", "GOV-COMPLETE-ONLY", "", "SER-GOV", "MAC-GOV"],
    ]
    discrepancy, content = _active_app_discrepancy(rows)
    _post_disposition(client_with_temp_app_db, discrepancy, note="Documented as expected.", reviewed=True)

    response = _post_inventory(client_with_temp_app_db, content, "same discrepancy.csv")

    assert response.status_code == 200
    assert b"RECONCILIATION COMPLETE" in response.data
    assert b"Documented as expected." in response.data
    assert b"operator-recon-complete" in response.data


def test_inventory_reconciliation_changed_or_new_discrepancy_does_not_inherit_disposition(client_with_temp_app_db) -> None:
    _login_role(client_with_temp_app_db, username="operator-recon-new-key", role="operator")
    _insert_app_asset("MATCH-NEWKEY", "SER-MATCH")
    original_rows = [
        ["Laptop", "MATCH-NEWKEY", "", "SER-MATCH", "MAC-MATCH"],
        ["Laptop", "GOV-NEWKEY-ONLY", "", "SER-GOV-1", "MAC-GOV-1"],
    ]
    changed_rows = [
        ["Laptop", "MATCH-NEWKEY", "", "SER-MATCH", "MAC-MATCH"],
        ["Laptop", "GOV-NEWKEY-ONLY", "", "SER-GOV-2", "MAC-GOV-1"],
        ["Laptop", "GOV-NEWKEY-ADDED", "", "SER-GOV-ADDED", "MAC-GOV-ADDED"],
    ]
    original_discrepancy, _content = _active_app_discrepancy(original_rows)
    changed_discrepancy, changed_content = _active_app_discrepancy(changed_rows)
    _post_disposition(client_with_temp_app_db, original_discrepancy, note="Old evidence reviewed.", reviewed=True)

    response = _post_inventory(client_with_temp_app_db, changed_content, "changed discrepancy.csv")

    assert changed_discrepancy.key != original_discrepancy.key
    assert response.status_code == 200
    assert b"RECONCILIATION REQUIRES ATTENTION" in response.data
    assert b"Old evidence reviewed." not in response.data
    assert b"No disposition saved for this active discrepancy." in response.data
