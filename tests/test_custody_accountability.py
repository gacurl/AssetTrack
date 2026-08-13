from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import assettrack.db as db
from assettrack.custody_accountability import build_custody_accountability_report


GENERATED_AT = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


class CustodyAccountabilityTests(unittest.TestCase):
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

    def _digest(self) -> str:
        return hashlib.sha256(self.db_path.read_bytes()).hexdigest()

    def _insert_holder(self, holder_id: int, name: str, organization: str) -> None:
        self.conn.execute(
            """
            INSERT INTO holders (
                id, holder_type, name, organization, identifier, email, contact_info, created_at, updated_at
            )
            VALUES (?, 'PERSON', ?, ?, ?, '', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """,
            (holder_id, name, organization, f"H-{holder_id}"),
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
        event_date: str,
        *,
        holder_id: int | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
            VALUES (?, ?, ?, 'test', NULL, '{}', ?);
            """,
            (asset_tag, event_type, event_date, holder_id),
        )
        self.conn.commit()

    def _report(self):
        return build_custody_accountability_report(self.conn, generated_at=GENERATED_AT)

    def test_single_issue_return_interval(self) -> None:
        self._insert_holder(1, "Alice Holder", "Mission A")
        self._insert_asset("AT-1", serial_number="SER-1", equipment_type="laptop")
        self._insert_event("AT-1", "ISSUE", "2026-01-01T00:00:00Z", holder_id=1)
        self._insert_event("AT-1", "RETURN", "2026-01-03T06:00:00Z")

        report = self._report()
        asset = report.assets[0]

        self.assertEqual(report.active_assets, 1)
        self.assertEqual(report.checked_in, 1)
        self.assertEqual(asset.asset_tag, "AT-1")
        self.assertEqual(asset.serial_number, "SER-1")
        self.assertEqual(asset.equipment_type, "laptop")
        self.assertEqual(asset.issue_count, 1)
        self.assertEqual(len(asset.intervals), 1)
        self.assertEqual(asset.intervals[0].holder.holder_id, 1)
        self.assertEqual(asset.intervals[0].holder.organization, "Mission A")
        self.assertEqual(asset.intervals[0].elapsed, timedelta(days=2, hours=6))
        self.assertFalse(asset.intervals[0].outstanding)

    def test_multiple_intervals_total_and_longest(self) -> None:
        self._insert_holder(1, "Alice Holder", "Mission A")
        self._insert_asset("AT-2")
        self._insert_event("AT-2", "ISSUE", "2026-01-01T00:00:00Z", holder_id=1)
        self._insert_event("AT-2", "RETURN", "2026-01-02T00:00:00Z")
        self._insert_event("AT-2", "ISSUE", "2026-01-05T00:00:00Z", holder_id=1)
        self._insert_event("AT-2", "RETURN", "2026-01-08T12:00:00Z")

        asset = self._report().assets[0]

        self.assertEqual(asset.issue_count, 2)
        self.assertEqual(len(asset.intervals), 2)
        self.assertEqual(asset.total_custody_duration, timedelta(days=4, hours=12))
        self.assertEqual(asset.longest_custody_interval, timedelta(days=3, hours=12))

    def test_outstanding_interval_uses_fixed_generation_timestamp(self) -> None:
        self._insert_holder(2, "Bob Holder", "Mission B")
        self._insert_asset("AT-3", location_type="IN_CUSTODY", current_holder_id=2)
        self._insert_event("AT-3", "ISSUE", "2026-01-09T12:00:00Z", holder_id=2)

        first = self._report()
        second = self._report()
        asset = first.assets[0]

        self.assertEqual(first, second)
        self.assertEqual(first.checked_out, 1)
        self.assertEqual(asset.current_accountability_state, "not_checked_in")
        self.assertEqual(asset.intervals[0].elapsed, timedelta(days=1))
        self.assertTrue(asset.intervals[0].outstanding)

    def test_holder_summary_multiple_holders(self) -> None:
        self._insert_holder(1, "Alice Holder", "Mission A")
        self._insert_holder(2, "Bob Holder", "Mission B")
        self._insert_asset("AT-4")
        self._insert_asset("AT-5")
        self._insert_event("AT-4", "ISSUE", "2026-01-01T00:00:00Z", holder_id=1)
        self._insert_event("AT-4", "RETURN", "2026-01-02T00:00:00Z")
        self._insert_event("AT-4", "ISSUE", "2026-01-03T00:00:00Z", holder_id=2)
        self._insert_event("AT-4", "RETURN", "2026-01-04T12:00:00Z")
        self._insert_event("AT-5", "ISSUE", "2026-01-05T00:00:00Z", holder_id=2)
        self._insert_event("AT-5", "RETURN", "2026-01-06T00:00:00Z")

        holders = {summary.holder.holder_id: summary for summary in self._report().holders}

        self.assertEqual(holders[1].unique_asset_tags, ("AT-4",))
        self.assertEqual(holders[1].issue_transaction_count, 1)
        self.assertEqual(holders[1].total_custody_time, timedelta(days=1))
        self.assertEqual(holders[2].unique_asset_tags, ("AT-4", "AT-5"))
        self.assertEqual(holders[2].issue_transaction_count, 2)
        self.assertEqual(holders[2].total_custody_time, timedelta(days=2, hours=12))
        self.assertEqual(holders[2].longest_custody_interval, timedelta(days=1, hours=12))

    def test_unpairable_history_surfaces_exception(self) -> None:
        self._insert_asset("AT-BAD")
        self._insert_event("AT-BAD", "RETURN", "2026-01-02T00:00:00Z")

        report = self._report()
        asset = report.assets[0]

        self.assertEqual(report.unresolved, 1)
        self.assertIn("RETURN event", asset.exceptions[0])
        self.assertIn("no preceding open ISSUE", asset.exceptions[0])

    def test_retired_and_disposed_assets_are_excluded(self) -> None:
        self._insert_asset("ACTIVE-1")
        self._insert_asset("RET-1", location_type="RETIRED")
        self._insert_asset("DISP-1", location_type="DISPOSED")
        self._insert_event("ACTIVE-1", "ASSET_CREATED", "2026-01-01T00:00:00Z")

        report = self._report()

        self.assertEqual(report.active_assets, 1)
        self.assertEqual([asset.asset_tag for asset in report.assets], ["ACTIVE-1"])

    def test_current_storage_location_uses_home_slot_when_supported(self) -> None:
        self._insert_slot(10, "CASE-1", 7)
        self._insert_asset("AT-SLOT", home_slot_id=10)
        self._insert_event("AT-SLOT", "ASSET_CREATED", "2026-01-01T00:00:00Z")

        asset = self._report().assets[0]

        self.assertEqual(asset.current_storage_location, "CASE-1 / Slot 7")

    def test_calculation_is_read_only(self) -> None:
        self._insert_asset("READONLY-1")
        self._insert_event("READONLY-1", "ASSET_CREATED", "2026-01-01T00:00:00Z")
        before_digest = self._digest()
        before_counts = {
            table: int(self.conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0])
            for table in ("assets", "asset_events", "slots", "holders")
        }

        report = self._report()

        after_counts = {
            table: int(self.conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0])
            for table in ("assets", "asset_events", "slots", "holders")
        }
        self.assertEqual(report.checked_in, 1)
        self.assertEqual(before_counts, after_counts)
        self.assertEqual(before_digest, self._digest())


if __name__ == "__main__":
    unittest.main()
