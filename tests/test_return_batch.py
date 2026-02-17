# file: tests/test_return_batch.py
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import assettrack.db as db
from assettrack.intake import app as intake_app


class ReturnBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "assettrack.db"
        self.conn = db.get_connection()
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL UNIQUE,
                location_type TEXT NULL,
                current_holder_id INTEGER NULL,
                home_slot_id INTEGER NULL
            );
            """
        )
        self.conn.commit()
        self.client = intake_app.app.test_client()
        intake_app.app.testing = True
        intake_app.SCAN_QUEUE.clear()

    def tearDown(self) -> None:
        intake_app.SCAN_QUEUE.clear()
        self.conn.close()
        self.temp_dir.cleanup()

    def _insert_asset(self, asset_tag: str, *, location_type: str, holder_id: int | None, home_slot_id: int) -> None:
        self.conn.execute(
            """
            INSERT INTO assets (asset_tag, location_type, current_holder_id, home_slot_id)
            VALUES (?, ?, ?, ?);
            """,
            (asset_tag, location_type, holder_id, home_slot_id),
        )
        self.conn.commit()

    def _insert_slot(self, slot_id: int, case_name: str, slot_position: int, current_asset_tag: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (?, ?, ?, ?);
            """,
            (slot_id, case_name, slot_position, current_asset_tag),
        )
        self.conn.commit()

    def test_return_routes_block_and_commit(self) -> None:
        self._insert_slot(10, "A", 1, None)
        self._insert_slot(20, "B", 2, None)
        self._insert_asset("TAG-VALID", location_type="IN_CUSTODY", holder_id=5, home_slot_id=10)
        self._insert_asset("TAG-OK", location_type="IN_CUSTODY", holder_id=9, home_slot_id=20)

        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="TAG-VALID", equipment_type="laptop"))

        render = self.client.get("/return")
        self.assertEqual(render.status_code, 200)
        self.assertIn(b"Return Assets", render.data)

        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="TAG-VALID", equipment_type="laptop"))
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="UNKNOWN", equipment_type="laptop"))

        blocked = self.client.post("/return/commit?json=1")
        self.assertEqual(blocked.status_code, 400)
        self.assertFalse(blocked.json["ok"])
        self.assertEqual(blocked.json["committed"], 0)

        valid_asset = self.conn.execute(
            "SELECT location_type, current_holder_id FROM assets WHERE asset_tag = ?;",
            ("TAG-VALID",),
        ).fetchone()
        self.assertEqual(valid_asset["location_type"], "IN_CUSTODY")
        self.assertEqual(valid_asset["current_holder_id"], 5)
        slot_after_block = self.conn.execute(
            "SELECT current_asset_tag FROM slots WHERE id = ?;",
            (10,),
        ).fetchone()
        self.assertIsNone(slot_after_block["current_asset_tag"])

        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="TAG-OK", equipment_type="laptop"))

        success = self.client.post("/return/commit?json=1")
        self.assertEqual(success.status_code, 200)
        self.assertTrue(success.json["ok"])
        self.assertEqual(success.json["committed"], 1)
        self.assertEqual(success.json["error"], None)
        self.assertEqual(len(intake_app.SCAN_QUEUE), 0)

        asset_after = self.conn.execute(
            "SELECT location_type, current_holder_id FROM assets WHERE asset_tag = ?;",
            ("TAG-OK",),
        ).fetchone()
        self.assertEqual(asset_after["location_type"], "STORAGE")
        self.assertIsNone(asset_after["current_holder_id"])

        slot_after = self.conn.execute(
            "SELECT current_asset_tag FROM slots WHERE id = ?;",
            (20,),
        ).fetchone()
        self.assertEqual(slot_after["current_asset_tag"], "TAG-OK")

        event_row = self.conn.execute(
            """
            SELECT event_type FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            ("TAG-OK",),
        ).fetchone()
        self.assertIsNotNone(event_row)
        self.assertEqual(event_row["event_type"], "STOCK_IN")


if __name__ == "__main__":
    unittest.main()
