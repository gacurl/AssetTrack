from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import assettrack.db as db
from assettrack.dashboard import build_dashboard_data
from assettrack.intake import app as intake_app


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "assettrack.db"
        self.conn = db.get_connection()
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL UNIQUE,
                serial_number TEXT NULL,
                manufacturer TEXT NULL,
                equipment_type TEXT NOT NULL,
                building TEXT NULL,
                room TEXT NULL,
                model TEXT NULL,
                model_code TEXT NULL,
                notes TEXT NULL,
                building_room TEXT NULL,
                custody_state TEXT NOT NULL,
                accountability_status TEXT NOT NULL,
                condition TEXT NOT NULL,
                created_date TEXT NOT NULL,
                updated_date TEXT NULL,
                location_type TEXT NULL,
                current_holder_id INTEGER NULL,
                home_slot_id INTEGER NULL
            );
            """
        )
        self.conn.commit()
        intake_app.app.testing = True
        self.client = intake_app.app.test_client()

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def _insert_holder(self, holder_id: int, name: str) -> None:
        now = "2026-01-01T00:00:00Z"
        self.conn.execute(
            """
            INSERT INTO holders (id, holder_type, name, identifier, contact_info, created_at, updated_at)
            VALUES (?, 'PERSON', ?, NULL, NULL, ?, ?);
            """,
            (holder_id, name, now, now),
        )

    def _insert_asset(
        self,
        asset_tag: str,
        *,
        location_type: str,
        home_slot_id: int | None = None,
        current_holder_id: int | None = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO assets (
                asset_tag,
                serial_number,
                manufacturer,
                equipment_type,
                building,
                room,
                building_room,
                custody_state,
                accountability_status,
                condition,
                created_date,
                updated_date,
                location_type,
                current_holder_id,
                home_slot_id
            )
            VALUES (?, ?, 'Dell', 'laptop', 'HQ', '100', 'HQ/100', 'in_stock', 'accountable', 'serviceable', '2026-01-01', '2026-01-01T00:00:00Z', ?, ?, ?);
            """,
            (asset_tag, f"SN-{asset_tag}", location_type, current_holder_id, home_slot_id),
        )
        return int(cursor.lastrowid)

    def _insert_slot(self, slot_id: int, case_name: str, slot_position: int) -> None:
        self.conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (?, ?, ?, NULL);
            """,
            (slot_id, case_name, slot_position),
        )

    def _insert_stock_out(self, asset_tag: str, event_date: str) -> None:
        self.conn.execute(
            """
            INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
            VALUES (?, 'STOCK_OUT', ?, 'tester', NULL, NULL, NULL);
            """,
            (asset_tag, event_date),
        )

    def _replace_slot_occupancy_without_unique_constraints(self) -> None:
        self.conn.execute("DROP TABLE slot_occupancy;")
        self.conn.execute(
            """
            CREATE TABLE slot_occupancy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slot_id INTEGER NOT NULL,
                asset_id INTEGER NOT NULL,
                assigned_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def test_dashboard_route_smoke_renders_summary_sections(self) -> None:
        self._insert_holder(1, "Alex Holder")
        self._insert_slot(10, "CASE-A", 1)
        storage_asset_id = self._insert_asset("AT-STORED", location_type="STORAGE", home_slot_id=10)
        self._insert_asset("AT-UNSLOT", location_type="STORAGE", home_slot_id=None)
        self._insert_asset("AT-CUST", location_type="IN_CUSTODY", current_holder_id=1)
        self._insert_asset("AT-DISP", location_type="DISPOSED")
        self.conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (10, ?, '2026-01-01T00:00:00Z');
            """,
            (storage_asset_id,),
        )
        self._insert_stock_out("AT-CUST", "2025-12-01T00:00:00Z")
        self.conn.commit()

        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Dashboard Summary Metrics", response.data)
        self.assertIn(b"Inventory Summary", response.data)
        self.assertIn(b"Slot Summary", response.data)
        self.assertIn(b"Custody Summary", response.data)
        self.assertIn(b"Exceptions Summary", response.data)
        self.assertIn(b"Top Custody Holders", response.data)
        self.assertIn(b"Case Utilization", response.data)
        self.assertIn(b"Exceptions Preview", response.data)

    def test_dashboard_metrics_use_distinct_and_most_recent_stock_out(self) -> None:
        self._replace_slot_occupancy_without_unique_constraints()
        self._insert_holder(1, "Alpha")
        self._insert_holder(2, "Bravo")

        self._insert_slot(1, "CASE-X", 1)
        self._insert_slot(2, "CASE-X", 2)

        asset_old = self._insert_asset("AT-OLD", location_type="IN_CUSTODY", current_holder_id=1)
        asset_recent = self._insert_asset("AT-RECENT", location_type="IN_CUSTODY", current_holder_id=1)
        asset_noevent = self._insert_asset("AT-NOEVENT", location_type="IN_CUSTODY", current_holder_id=2)
        asset_storage = self._insert_asset("AT-STORAGE", location_type="STORAGE", home_slot_id=2)

        self.conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES
                (1, ?, '2026-01-01T00:00:00Z'),
                (1, ?, '2026-01-02T00:00:00Z'),
                (2, ?, '2026-01-03T00:00:00Z');
            """,
            (asset_old, asset_recent, asset_storage),
        )

        self._insert_stock_out("AT-OLD", "2026-01-01T00:00:00Z")
        self._insert_stock_out("AT-RECENT", "2026-01-01T00:00:00Z")
        self._insert_stock_out("AT-RECENT", "2026-02-10T00:00:00Z")
        self.conn.commit()

        data = build_dashboard_data(
            self.conn,
            custody_days_threshold=30,
            now_utc=datetime(2026, 2, 20, 0, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(data["summary"]["slots"]["occupied_slots"], 2)
        self.assertEqual(data["summary"]["exceptions"]["slot_conflicts"], 1)
        self.assertEqual(data["summary"]["exceptions"]["in_custody_over_threshold"], 1)

        overdue_rows = data["snapshots"]["exceptions"]["in_custody_over_threshold"]
        self.assertEqual(len(overdue_rows), 1)
        self.assertEqual(overdue_rows[0]["asset_tag"], "AT-OLD")
        self.assertEqual(overdue_rows[0]["days_out"], 50)

    def test_root_redirects_to_dashboard(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))
        self.assertTrue(resp.headers["Location"].endswith("/dashboard"))

