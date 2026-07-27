from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from assettrack.db import bootstrap_db
from assettrack.network_asset_import import LEGACY_NETWORK_CSV_CLI_WARNING, import_network_assets_csv


class NetworkAssetImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "assettrack.db"
        bootstrap_db(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _write_csv(self, content: str) -> Path:
        path = Path(self.temp_dir.name) / "network.csv"
        path.write_text(content, encoding="utf-8")
        return path

    def _insert_slot(self, case_name: str, slot_position: int, *, current_asset_tag: str | None = None) -> None:
        conn = self._connection()
        try:
            conn.execute(
                "INSERT INTO slots (case_name, slot_position, current_asset_tag) VALUES (?, ?, ?);",
                (case_name, slot_position, current_asset_tag),
            )
            conn.commit()
        finally:
            conn.close()

    def _import(self, content: str):
        return import_network_assets_csv(self._write_csv(content), db_path=self.db_path, actor="admin-import")

    def test_import_creates_switch_with_existing_slot_and_append_only_events(self) -> None:
        self._insert_slot("CASE-NET", 2)
        report = self._import(
            "asset_tag,barcode,serial_number,equipment_type,manufacturer,model,location_building,case_identifier,slot_identifier,notes_comments\n"
            "SW-100,,SER-100,switch,Cisco,C9300,HQ,CASE-NET,2,Reviewed staging row\n"
        )

        self.assertEqual(report.summary(), {"processed": 1, "imported": 1, "errors": 0})
        conn = self._connection()
        try:
            asset = conn.execute(
                """
                SELECT asset_tag, serial_number, equipment_type, manufacturer, model, building, room, home_slot_id, location_type
                FROM assets WHERE asset_tag = 'SW-100';
                """
            ).fetchone()
            self.assertIsNotNone(asset)
            self.assertEqual(asset["manufacturer"], "Cisco")
            self.assertEqual(asset["building"], "HQ")
            self.assertIsNone(asset["room"])
            self.assertEqual(asset["location_type"], "STORAGE")
            self.assertIsNotNone(asset["home_slot_id"])
            events = conn.execute(
                "SELECT event_type FROM asset_events WHERE asset_tag = 'SW-100' ORDER BY id;"
            ).fetchall()
            self.assertEqual([row["event_type"] for row in events], ["created", "SLOT_ASSIGN", "SCAN"])
        finally:
            conn.close()

    def test_barcode_fills_blank_asset_tag(self) -> None:
        report = self._import(
            "asset_tag,barcode,serial_number,equipment_type,manufacturer,model,location_building,case_identifier,slot_identifier,notes_comments\n"
            ",RTR-200,SER-200,router,,MX204,,,,\n"
        )

        self.assertEqual(report.summary(), {"processed": 1, "imported": 1, "errors": 0})
        conn = self._connection()
        try:
            asset = conn.execute(
                """
                SELECT asset_tag, manufacturer, building, room, building_room
                FROM assets
                WHERE asset_tag = 'RTR-200';
                """
            ).fetchone()
            self.assertIsNotNone(asset)
            self.assertEqual(asset["manufacturer"], "")
            self.assertEqual(asset["building"], "")
            self.assertIsNone(asset["room"])
            self.assertIsNone(asset["building_room"])
            event = conn.execute(
                """
                SELECT payload
                FROM asset_events
                WHERE asset_tag = 'RTR-200'
                  AND event_type = 'SCAN'
                LIMIT 1;
                """
            ).fetchone()
            self.assertIsNotNone(event)
            self.assertNotIn("Unknown", event["payload"])
            self.assertNotIn("N/A", event["payload"])
            self.assertNotIn("None", event["payload"])
            self.assertNotIn("Not Provided", event["payload"])
        finally:
            conn.close()

    def test_serial_only_row_is_rejected(self) -> None:
        report = self._import(
            "asset_tag,barcode,serial_number,equipment_type\n"
            ",,SER-ONLY,switch\n"
        )

        self.assertEqual(report.summary(), {"processed": 1, "imported": 0, "errors": 1})
        self.assertIn("asset_tag is required", report.errors[0])

    def test_duplicate_canonical_asset_tag_is_rejected_before_commit(self) -> None:
        report = self._import(
            "asset_tag,barcode,serial_number,equipment_type\n"
            "SW-DUP,,,switch\n"
            ",SW-DUP,,router\n"
        )

        self.assertEqual(report.summary(), {"processed": 2, "imported": 0, "errors": 1})
        self.assertIn("duplicate canonical asset_tag", report.errors[0])

    def test_existing_serial_number_is_rejected(self) -> None:
        first = self._import(
            "asset_tag,barcode,serial_number,equipment_type\n"
            "SW-FIRST,,SER-DUP,switch\n"
        )
        self.assertEqual(first.summary(), {"processed": 1, "imported": 1, "errors": 0})

        second = self._import(
            "asset_tag,barcode,serial_number,equipment_type\n"
            "SW-SECOND,,ser-dup,switch\n"
        )
        self.assertEqual(second.summary(), {"processed": 1, "imported": 0, "errors": 1})
        self.assertIn("serial_number already exists", second.errors[0])

    def test_duplicate_serial_number_in_csv_is_rejected_before_commit(self) -> None:
        report = self._import(
            "asset_tag,serial_number,equipment_type\n"
            "SW-SER-1,SER-SAME,switch\n"
            "SW-SER-2,ser-same,router\n"
        )

        self.assertEqual(report.summary(), {"processed": 2, "imported": 0, "errors": 1})
        self.assertIn("duplicate serial_number", report.errors[0])

    def test_rejected_cmdb_column_blocks_import(self) -> None:
        report = self._import(
            "asset_tag,equipment_type,ip_address\n"
            "SW-IP,switch,192.0.2.10\n"
        )

        self.assertEqual(report.summary(), {"processed": 0, "imported": 0, "errors": 1})
        self.assertEqual(report.errors, ("Rejected CMDB-like CSV columns: ip_address",))

    def test_invalid_case_slot_reference_is_rejected(self) -> None:
        report = self._import(
            "asset_tag,equipment_type,case_identifier,slot_identifier\n"
            "SW-NO-SLOT,switch,CASE-MISSING,1\n"
        )

        self.assertEqual(report.summary(), {"processed": 1, "imported": 0, "errors": 1})
        self.assertIn("does not reference an existing slot", report.errors[0])

    def test_non_numeric_slot_identifier_is_rejected(self) -> None:
        report = self._import(
            "asset_tag,equipment_type,case_identifier,slot_identifier\n"
            "SW-BAD-SLOT,switch,CASE-NET,slot-two\n"
        )

        self.assertEqual(report.summary(), {"processed": 1, "imported": 0, "errors": 1})
        self.assertIn("slot_identifier must be numeric", report.errors[0])

    def test_occupied_slot_is_rejected(self) -> None:
        self._insert_slot("CASE-BUSY", 1, current_asset_tag="EXISTING-ASSET")
        report = self._import(
            "asset_tag,equipment_type,case_identifier,slot_identifier\n"
            "SW-BUSY,switch,CASE-BUSY,1\n"
        )

        self.assertEqual(report.summary(), {"processed": 1, "imported": 0, "errors": 1})
        self.assertIn("selected slot is already occupied", report.errors[0])

    def test_unsupported_equipment_type_is_rejected(self) -> None:
        report = self._import(
            "asset_tag,equipment_type\n"
            "AP-100,access point\n"
        )

        self.assertEqual(report.summary(), {"processed": 1, "imported": 0, "errors": 1})
        self.assertIn("equipment_type must be switch or router", report.errors[0])

    def test_script_entrypoint_runs_end_to_end(self) -> None:
        csv_path = self._write_csv(
            "asset_tag,equipment_type\n"
            "SW-CLI,switch\n"
        )
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "import_network_assets_csv.py"

        result = subprocess.run(
            [sys.executable, str(script_path), str(csv_path), "--db", str(self.db_path), "--actor", "admin-import"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), '{"errors": 0, "imported": 1, "processed": 1}')
        self.assertEqual(result.stderr.count(LEGACY_NETWORK_CSV_CLI_WARNING), 1)

    def test_script_entrypoint_warns_once_and_preserves_failure_exit_code(self) -> None:
        csv_path = self._write_csv(
            "asset_tag,equipment_type,ip_address\n"
            "SW-IP,switch,192.0.2.10\n"
        )
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "import_network_assets_csv.py"

        result = subprocess.run(
            [sys.executable, str(script_path), str(csv_path), "--db", str(self.db_path), "--actor", "admin-import"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout.strip(), '{"errors": 1, "imported": 0, "processed": 0}')
        self.assertEqual(result.stderr.count(LEGACY_NETWORK_CSV_CLI_WARNING), 1)
        self.assertIn("Rejected CMDB-like CSV columns: ip_address", result.stderr)


if __name__ == "__main__":
    unittest.main()
