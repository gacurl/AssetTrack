from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

import assettrack.db as db
from assettrack.intake import app as intake_app


class AdminCreateAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "assettrack.db"
        self.conn = db.get_connection()
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL UNIQUE,
                equipment_type TEXT NOT NULL,
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
        self.orig_admin_users = os.environ.get("ASSETTRACK_ADMIN_USERS")
        os.environ["ASSETTRACK_ADMIN_USERS"] = "admin:test-pass"
        intake_app.app.testing = True
        self.client = intake_app.app.test_client()

    def tearDown(self) -> None:
        if self.orig_admin_users is None:
            os.environ.pop("ASSETTRACK_ADMIN_USERS", None)
        else:
            os.environ["ASSETTRACK_ADMIN_USERS"] = self.orig_admin_users
        self.conn.close()
        self.temp_dir.cleanup()

    def _insert_slot(self, slot_id: int, *, current_asset_tag: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (?, 'CASE-A', ?, ?);
            """,
            (slot_id, slot_id, current_asset_tag),
        )
        self.conn.commit()

    def _insert_asset(self, asset_tag: str) -> None:
        self.conn.execute(
            """
            INSERT INTO assets (
                asset_tag,
                equipment_type,
                custody_state,
                accountability_status,
                condition,
                created_date,
                location_type,
                current_holder_id,
                home_slot_id
            )
            VALUES (?, 'laptop', 'in_stock', 'accountable', 'serviceable', '2026-01-01', 'STORAGE', NULL, NULL);
            """,
            (asset_tag,),
        )
        self.conn.commit()

    def _admin_headers(self) -> dict[str, str]:
        token = base64.b64encode(b"admin:test-pass").decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def test_create_asset_unslotted_success(self) -> None:
        response = self.client.post(
            "/admin/assets/create",
            headers=self._admin_headers(),
            json={
                "asset_tag": "AT-100",
                "actor": "admin-user",
                "equipment_type": "laptop",
                "notes": "initial load",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["ok"])

        asset_row = self.conn.execute(
            """
            SELECT id, asset_tag, location_type, current_holder_id, home_slot_id, equipment_type
            FROM assets
            WHERE asset_tag = ?;
            """,
            ("AT-100",),
        ).fetchone()
        self.assertIsNotNone(asset_row)
        self.assertEqual(asset_row["location_type"], "STORAGE")
        self.assertIsNone(asset_row["current_holder_id"])
        self.assertIsNone(asset_row["home_slot_id"])
        self.assertEqual(asset_row["equipment_type"], "laptop")

        occ = self.conn.execute("SELECT 1 FROM slot_occupancy WHERE asset_id = ?;", (asset_row["id"],)).fetchone()
        self.assertIsNone(occ)

        event = self.conn.execute(
            """
            SELECT event_type, actor, notes, payload
            FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            ("AT-100",),
        ).fetchone()
        self.assertIsNotNone(event)
        self.assertEqual(event["event_type"], "ASSET_CREATED")
        self.assertEqual(event["actor"], "admin-user")
        payload = json.loads(event["payload"])
        self.assertEqual(payload["equipment_type"], "laptop")

    def test_create_asset_allows_missing_equipment_type(self) -> None:
        response = self.client.post(
            "/admin/assets/create",
            headers=self._admin_headers(),
            json={
                "asset_tag": "AT-101",
                "actor": "admin-user",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["ok"])

        asset_row = self.conn.execute(
            "SELECT equipment_type FROM assets WHERE asset_tag = ?;",
            ("AT-101",),
        ).fetchone()
        self.assertIsNotNone(asset_row)
        self.assertEqual(asset_row["equipment_type"], "")

        event = self.conn.execute(
            """
            SELECT payload
            FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            ("AT-101",),
        ).fetchone()
        self.assertIsNotNone(event)
        self.assertIsNone(event["payload"])

    def test_create_asset_with_home_slot_success(self) -> None:
        self._insert_slot(11)

        response = self.client.post(
            "/admin/assets/create",
            headers=self._admin_headers(),
            json={
                "asset_tag": "AT-200",
                "actor": "admin-user",
                "equipment_type": "tablet",
                "home_slot_id": 11,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["ok"])
        self.assertEqual(response.json["home_slot_id"], 11)

        asset_row = self.conn.execute(
            """
            SELECT id, home_slot_id, location_type, current_holder_id
            FROM assets
            WHERE asset_tag = ?;
            """,
            ("AT-200",),
        ).fetchone()
        self.assertIsNotNone(asset_row)
        self.assertEqual(asset_row["home_slot_id"], 11)
        self.assertEqual(asset_row["location_type"], "STORAGE")
        self.assertIsNone(asset_row["current_holder_id"])

        occ = self.conn.execute(
            """
            SELECT slot_id
            FROM slot_occupancy
            WHERE asset_id = ?;
            """,
            (asset_row["id"],),
        ).fetchone()
        self.assertIsNotNone(occ)
        self.assertEqual(occ["slot_id"], 11)

        slot = self.conn.execute("SELECT current_asset_tag FROM slots WHERE id = ?;", (11,)).fetchone()
        self.assertEqual(slot["current_asset_tag"], "AT-200")

        event = self.conn.execute(
            """
            SELECT payload
            FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            ("AT-200",),
        ).fetchone()
        payload = json.loads(event["payload"])
        self.assertEqual(payload["slot_id"], 11)
        self.assertEqual(payload["equipment_type"], "tablet")

    def test_duplicate_asset_tag_rejected(self) -> None:
        self._insert_asset("AT-DUP")

        response = self.client.post(
            "/admin/assets/create",
            headers=self._admin_headers(),
            json={
                "asset_tag": "AT-DUP",
                "actor": "admin-user",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json["ok"])
        self.assertIn("already exists", response.json["error"])

        count = self.conn.execute("SELECT COUNT(*) AS c FROM assets WHERE asset_tag = ?;", ("AT-DUP",)).fetchone()
        self.assertEqual(count["c"], 1)

    def test_occupied_home_slot_rejected_and_rolls_back(self) -> None:
        self._insert_slot(22, current_asset_tag="EXISTING-ASSET")

        response = self.client.post(
            "/admin/assets/create",
            headers=self._admin_headers(),
            json={
                "asset_tag": "AT-300",
                "actor": "admin-user",
                "home_slot_id": 22,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json["ok"])
        self.assertIn("occupied", response.json["error"].lower())

        created = self.conn.execute("SELECT 1 FROM assets WHERE asset_tag = ?;", ("AT-300",)).fetchone()
        self.assertIsNone(created)

        event = self.conn.execute(
            "SELECT 1 FROM asset_events WHERE asset_tag = ? AND event_type = 'ASSET_CREATED';",
            ("AT-300",),
        ).fetchone()
        self.assertIsNone(event)


if __name__ == "__main__":
    unittest.main()
