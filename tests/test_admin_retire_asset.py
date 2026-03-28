# file: tests/test_admin_retire_asset.py
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


class AdminRetireAssetTests(unittest.TestCase):
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
                model TEXT NULL,
                location_type TEXT NULL,
                current_holder_id INTEGER NULL,
                home_slot_id INTEGER NULL,
                updated_date TEXT NULL
            );
            """
        )
        self.conn.commit()
        intake_app.app.testing = True
        intake_app.SCAN_QUEUE.clear()
        self.client = intake_app.app.test_client()
        admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
        login_session(self.client, admin_user_id)

    def tearDown(self) -> None:
        intake_app.SCAN_QUEUE.clear()
        self.conn.close()
        self.temp_dir.cleanup()

    def _insert_slot(self, slot_id: int, case_name: str, slot_position: int, current_asset_tag: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (?, ?, ?, ?);
            """,
            (slot_id, case_name, slot_position, current_asset_tag),
        )
        self.conn.commit()

    def _insert_asset(
        self,
        asset_tag: str,
        *,
        location_type: str,
        holder_id: int | None = None,
        home_slot_id: int | None = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO assets (
                asset_tag,
                serial_number,
                manufacturer,
                model,
                location_type,
                current_holder_id,
                home_slot_id,
                updated_date
            )
            VALUES (?, 'SERIAL', 'Vendor', 'Model-X', ?, ?, ?, NULL);
            """,
            (asset_tag, location_type, holder_id, home_slot_id),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def test_get_retire_route_allows_admin(self) -> None:
        response = self.client.get("/admin/assets/retire")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin: Retire Asset", response.data)

    def test_retire_from_storage_is_atomic_and_logs_event(self) -> None:
        self._insert_slot(10, "CASE-A", 1, current_asset_tag="RET-100")
        asset_id = self._insert_asset("RET-100", location_type="STORAGE", holder_id=None, home_slot_id=10)
        self.conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (10, ?, '2026-02-01T00:00:00Z');
            """,
            (asset_id,),
        )
        self.conn.commit()

        response = self.client.post(
            "/admin/assets/retire",
            data={
                "action": "retire",
                "asset_tag": "RET-100",
                "failure_type": "HARDWARE",
                "notes": "Motherboard failure confirmed.",
                "confirm_physical": "yes",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Retired asset RET-100 with status DISPOSED.", response.data)

        asset = self.conn.execute(
            "SELECT location_type, current_holder_id, home_slot_id FROM assets WHERE id = ?;",
            (asset_id,),
        ).fetchone()
        self.assertEqual(asset["location_type"], "DISPOSED")
        self.assertIsNone(asset["current_holder_id"])
        self.assertIsNone(asset["home_slot_id"])

        occ = self.conn.execute("SELECT 1 FROM slot_occupancy WHERE asset_id = ?;", (asset_id,)).fetchone()
        self.assertIsNone(occ)
        slot = self.conn.execute("SELECT current_asset_tag FROM slots WHERE id = 10;").fetchone()
        self.assertIsNone(slot["current_asset_tag"])

        event = self.conn.execute(
            """
            SELECT event_type, actor, notes, payload
            FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            ("RET-100",),
        ).fetchone()
        self.assertEqual(event["event_type"], "ASSET_RETIRED")
        self.assertEqual(event["actor"], "admin")
        self.assertEqual(event["notes"], "Motherboard failure confirmed.")
        payload = json.loads(event["payload"])
        self.assertEqual(payload["failure_type"], "HARDWARE")
        self.assertEqual(payload["to_location_type"], "DISPOSED")

    def test_retire_from_in_custody_requires_extra_confirmation(self) -> None:
        self._insert_asset("RET-200", location_type="IN_CUSTODY", holder_id=51, home_slot_id=None)

        missing_confirm = self.client.post(
            "/admin/assets/retire",
            data={
                "action": "retire",
                "asset_tag": "RET-200",
                "failure_type": "LOST",
                "notes": "Lost during field operations.",
                "confirm_physical": "yes",
            },
        )
        self.assertEqual(missing_confirm.status_code, 200)
        self.assertIn(b"not recoverable", missing_confirm.data)

        ok = self.client.post(
            "/admin/assets/retire",
            data={
                "action": "retire",
                "asset_tag": "RET-200",
                "failure_type": "LOST",
                "notes": "Lost during field operations.",
                "confirm_physical": "yes",
                "confirm_in_field": "yes",
            },
            follow_redirects=True,
        )
        self.assertEqual(ok.status_code, 200)
        self.assertIn(b"Retired asset RET-200 with status DISPOSED.", ok.data)

        asset = self.conn.execute(
            "SELECT location_type, current_holder_id, home_slot_id FROM assets WHERE asset_tag = ?;",
            ("RET-200",),
        ).fetchone()
        self.assertEqual(asset["location_type"], "DISPOSED")
        self.assertIsNone(asset["current_holder_id"])
        self.assertIsNone(asset["home_slot_id"])

        event = self.conn.execute(
            """
            SELECT event_type, payload, holder_id
            FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            ("RET-200",),
        ).fetchone()
        self.assertEqual(event["event_type"], "ASSET_RETIRED_IN_FIELD")
        self.assertEqual(event["holder_id"], 51)
        payload = json.loads(event["payload"])
        self.assertEqual(payload["failure_type"], "LOST")

    def test_retired_assets_are_blocked_from_issue_and_return(self) -> None:
        self._insert_slot(20, "CASE-B", 2, current_asset_tag=None)
        self._insert_asset("RET-300", location_type="DISPOSED", holder_id=None, home_slot_id=20)

        with self.assertRaisesRegex(ValueError, "Retired/disposed"):
            intake_app._issue_batch(
                ["RET-300"],
                holder_id=4,
                issue_location={"building": "HQ North", "room": "210"},
                responsibility_ack={
                    "acknowledged": True,
                    "ack_holder_id": 4,
                    "ack_operator_user_id": 1,
                    "ack_at": "2026-03-28T00:00:00Z",
                    "ack_scope": "batch",
                },
            )

        with self.assertRaisesRegex(ValueError, "Retired/disposed"):
            intake_app._return_batch(
                ["RET-300"],
                responsibility_ack={
                    "acknowledged": True,
                    "ack_operator_user_id": 1,
                    "ack_at": "2026-03-28T00:00:00Z",
                    "ack_scope": "batch",
                },
            )

    def test_admin_assign_slot_refuses_retired_asset(self) -> None:
        self._insert_asset("RET-400", location_type="DISPOSED", holder_id=None, home_slot_id=None)

        response = self.client.post(
            "/admin/assign-slot",
            data={
                "action": "lookup",
                "asset_tag": "RET-400",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"retired/disposed", response.data)


if __name__ == "__main__":
    unittest.main()
