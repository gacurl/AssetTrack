from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import assettrack.db as db
from scripts import verify_accountability


class VerifyAccountabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "assettrack.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        db._create_schema(self.conn)
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def _insert_holder(self, holder_id: int, name: str) -> None:
        self.conn.execute(
            """
            INSERT INTO holders (
                id, holder_type, name, identifier, email, contact_info, created_at, updated_at
            )
            VALUES (?, 'PERSON', ?, ?, '', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """,
            (holder_id, name, f"H-{holder_id}"),
        )
        self.conn.commit()

    def _insert_slot(self, slot_id: int, case_name: str, slot_position: int) -> None:
        self.conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (?, ?, ?, NULL);
            """,
            (slot_id, case_name, slot_position),
        )
        self.conn.commit()

    def _insert_asset(
        self,
        asset_tag: str,
        *,
        serial_number: str = "SER",
        equipment_type: str = "laptop",
        location_type: str = "STORAGE",
        current_holder_id: int | None = None,
        home_slot_id: int | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO assets (
                asset_tag, serial_number, equipment_type, location_type, current_holder_id, home_slot_id
            )
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (asset_tag, serial_number, equipment_type, location_type, current_holder_id, home_slot_id),
        )
        self.conn.commit()

    def _insert_event(
        self,
        asset_tag: str,
        event_type: str,
        *,
        event_date: str = "2026-01-01T00:00:00Z",
        holder_id: int | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
            VALUES (?, ?, ?, 'test', NULL, NULL, ?);
            """,
            (asset_tag, event_type, event_date, holder_id),
        )
        self.conn.commit()

    def _run_main(self) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = verify_accountability.main(["--db", str(self.db_path)])
        return exit_code, output.getvalue()

    def _db_digest(self) -> str:
        return hashlib.sha256(self.db_path.read_bytes()).hexdigest()

    def test_all_active_assets_checked_in_passes_with_zero_exit(self) -> None:
        self._insert_asset("CHECKED-1", serial_number="SER-1", equipment_type="laptop")
        self._insert_asset("CHECKED-2", serial_number="SER-2", equipment_type="router")
        self._insert_event("CHECKED-1", "ASSET_CREATED")
        self._insert_event("CHECKED-2", "RETURN")

        exit_code, output = self._run_main()

        self.assertEqual(exit_code, 0)
        self.assertIn("Total active assets evaluated: 2", output)
        self.assertIn("Confirmed checked in: 2", output)
        self.assertIn("PASS: All 2 active assets are checked in and accounted for.", output)

    def test_one_issued_asset_is_identified_with_nonzero_exit(self) -> None:
        self._insert_holder(7, "Issued Holder")
        self._insert_asset("ISSUED-1", serial_number="SER-I", location_type="IN_CUSTODY", current_holder_id=7)
        self._insert_event("ISSUED-1", "ISSUE", holder_id=7)

        exit_code, output = self._run_main()

        self.assertEqual(exit_code, 1)
        self.assertIn("Not checked in: 1", output)
        self.assertIn("FAIL: 1 of 1 active assets are not confirmed checked in.", output)
        self.assertIn("ISSUED-1; classification=not_checked_in", output)
        self.assertIn("serial=SER-I", output)
        self.assertIn("holder=Issued Holder", output)

    def test_multiple_issued_assets_have_deterministic_totals_and_order(self) -> None:
        self._insert_holder(7, "Issued Holder")
        self._insert_asset("ZZ-ISSUED", location_type="IN_CUSTODY", current_holder_id=7)
        self._insert_asset("AA-ISSUED", location_type="IN_CUSTODY", current_holder_id=7)
        self._insert_asset("MM-CHECKED", location_type="STORAGE")
        self._insert_event("ZZ-ISSUED", "ISSUE", event_date="2026-01-02T00:00:00Z", holder_id=7)
        self._insert_event("AA-ISSUED", "ISSUE", event_date="2026-01-03T00:00:00Z", holder_id=7)
        self._insert_event("MM-CHECKED", "ASSET_CREATED")

        first_exit, first_output = self._run_main()
        second_exit, second_output = self._run_main()

        self.assertEqual(first_exit, 1)
        self.assertEqual(second_exit, 1)
        self.assertEqual(first_output, second_output)
        self.assertIn("Total active assets evaluated: 3", first_output)
        self.assertIn("Confirmed checked in: 1", first_output)
        self.assertIn("Not checked in: 2", first_output)
        self.assertLess(first_output.index("AA-ISSUED"), first_output.index("ZZ-ISSUED"))

    def test_returned_asset_is_checked_in(self) -> None:
        self._insert_asset("RETURNED-1", location_type="STORAGE")
        self._insert_event("RETURNED-1", "ISSUE", event_date="2026-01-01T00:00:00Z")
        self._insert_event("RETURNED-1", "RETURN", event_date="2026-01-02T00:00:00Z")

        result = verify_accountability.verify_accountability(self.conn)

        self.assertTrue(result.passes)
        self.assertEqual(len(result.confirmed_checked_in), 1)

    def test_inconsistent_custody_event_state_is_unresolved(self) -> None:
        self._insert_asset("BAD-STATE", location_type="STORAGE")
        self._insert_event("BAD-STATE", "ISSUE")

        exit_code, output = self._run_main()

        self.assertEqual(exit_code, 1)
        self.assertIn("Unresolved/inconsistent: 1", output)
        self.assertIn("BAD-STATE; classification=unresolved", output)
        self.assertIn("state is STORAGE but latest custody event is ISSUE", output)

    def test_asset_without_active_event_proof_is_unresolved(self) -> None:
        self._insert_asset("NO-EVENT", location_type="STORAGE")

        exit_code, output = self._run_main()

        self.assertEqual(exit_code, 1)
        self.assertIn("NO-EVENT; classification=unresolved", output)
        self.assertIn("state is STORAGE without active event proof", output)

    def test_retired_and_disposed_assets_are_excluded(self) -> None:
        self._insert_asset("ACTIVE-1", location_type="STORAGE")
        self._insert_asset("RET-1", location_type="RETIRED")
        self._insert_asset("DISP-1", location_type="DISPOSED")
        self._insert_event("ACTIVE-1", "ASSET_CREATED")

        exit_code, output = self._run_main()

        self.assertEqual(exit_code, 0)
        self.assertIn("Total active assets evaluated: 1", output)
        self.assertNotIn("RET-1", output)
        self.assertNotIn("DISP-1", output)

    def test_database_remains_unchanged_readonly(self) -> None:
        self._insert_slot(10, "CASE-1", 1)
        self._insert_holder(7, "Read Only Holder")
        self._insert_asset("READONLY-1", location_type="STORAGE", current_holder_id=7, home_slot_id=10)
        self._insert_event("READONLY-1", "ASSET_CREATED")
        before_digest = self._db_digest()
        before_counts = {
            table: int(self.conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0])
            for table in ("assets", "asset_events", "slots", "holders")
        }

        exit_code, output = self._run_main()

        after_counts = {
            table: int(self.conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0])
            for table in ("assets", "asset_events", "slots", "holders")
        }
        self.assertEqual(exit_code, 1)
        self.assertIn("storage=CASE-1 / Slot 1", output)
        self.assertEqual(before_counts, after_counts)
        self.assertEqual(before_digest, self._db_digest())


if __name__ == "__main__":
    unittest.main()
