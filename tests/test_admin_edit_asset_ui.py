from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


class AdminEditAssetUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "assettrack.db"
        self.conn = db.get_connection()
        intake_app.app.testing = True
        self.client = intake_app.app.test_client()
        admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
        login_session(self.client, admin_user_id)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def _insert_slot(self, slot_id: int, case_name: str, slot_position: int, *, current_asset_tag: str | None = None) -> None:
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
        serial_number: str,
        location_type: str,
        current_holder_id: int | None,
        home_slot_id: int | None,
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
                model,
                model_code,
                notes,
                building_room,
                custody_state,
                accountability_status,
                condition,
                created_date,
                updated_date,
                location_type,
                current_holder_id,
                home_slot_id,
                case_number,
                slot_number
            )
            VALUES (?, ?, 'Dell', 'laptop', 'HQ', '110', 'Latitude', '5400', 'seed', 'HQ/110', 'in_stock', 'accountable', 'serviceable', '2026-01-01', '2026-01-01T00:00:00Z', ?, ?, ?, NULL, NULL);
            """,
            (asset_tag, serial_number, location_type, current_holder_id, home_slot_id),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def _occupy_slot(self, slot_id: int, asset_id: int, asset_tag: str) -> None:
        self.conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (?, ?, '2026-01-02T00:00:00Z');
            """,
            (slot_id, asset_id),
        )
        self.conn.execute("UPDATE slots SET current_asset_tag = ? WHERE id = ?;", (asset_tag, slot_id))
        self.conn.commit()

    def test_get_admin_edit_asset_route_allows_admin(self) -> None:
        response = self.client.get("/admin/assets/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin: Edit Asset", response.data)

    def test_edit_storage_asset_moves_slot_and_persists_fields(self) -> None:
        self._insert_slot(201, "CASE-A", 1)
        self._insert_slot(202, "CASE-B", 2)
        asset_id = self._insert_asset(
            "AT-EDIT-1",
            serial_number="SER-EDIT-1",
            location_type="STORAGE",
            current_holder_id=None,
            home_slot_id=201,
        )
        self._occupy_slot(201, asset_id, "AT-EDIT-1")

        response = self.client.post(
            "/admin/assets/edit",
            data={
                "action": "update",
                "lookup_asset_tag": "AT-EDIT-1",
                "asset_tag": "AT-EDIT-1",
                "serial_number": "SER-EDIT-1A",
                "manufacturer": "Lenovo",
                "equipment_type": "tablet",
                "building": "HQ",
                "room": "210",
                "model": "X1",
                "model_code": "GEN9",
                "notes": "relocated",
                "case_name": "CASE-B",
                "slot_id": "202",
            },
        )
        self.assertEqual(response.status_code, 302)

        asset_row = self.conn.execute(
            """
            SELECT serial_number, manufacturer, equipment_type, building_room, home_slot_id, case_number, slot_number
            FROM assets
            WHERE id = ?;
            """,
            (asset_id,),
        ).fetchone()
        self.assertEqual(asset_row["serial_number"], "SER-EDIT-1A")
        self.assertEqual(asset_row["manufacturer"], "Lenovo")
        self.assertEqual(asset_row["equipment_type"], "tablet")
        self.assertEqual(asset_row["building_room"], "HQ/210")
        self.assertEqual(asset_row["home_slot_id"], 202)
        self.assertEqual(asset_row["case_number"], "CASE-B")
        self.assertEqual(asset_row["slot_number"], "2")

        occ = self.conn.execute("SELECT slot_id FROM slot_occupancy WHERE asset_id = ?;", (asset_id,)).fetchone()
        self.assertEqual(occ["slot_id"], 202)
        old_slot = self.conn.execute("SELECT current_asset_tag FROM slots WHERE id = 201;").fetchone()
        new_slot = self.conn.execute("SELECT current_asset_tag FROM slots WHERE id = 202;").fetchone()
        self.assertIsNone(old_slot["current_asset_tag"])
        self.assertEqual(new_slot["current_asset_tag"], "AT-EDIT-1")

        events = self.conn.execute(
            """
            SELECT event_type, payload
            FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id ASC;
            """,
            ("AT-EDIT-1",),
        ).fetchall()
        self.assertTrue(any(row["event_type"] == "ASSET_UPDATED" for row in events))
        payloads = [json.loads(row["payload"]) for row in events if row["payload"]]
        self.assertTrue(any(payload.get("home_slot_id") == 202 for payload in payloads))

    def test_edit_in_custody_asset_updates_home_slot_without_occupancy(self) -> None:
        self._insert_slot(301, "CASE-C", 3)
        self._insert_slot(302, "CASE-D", 4)
        asset_id = self._insert_asset(
            "AT-EDIT-2",
            serial_number="SER-EDIT-2",
            location_type="IN_CUSTODY",
            current_holder_id=77,
            home_slot_id=301,
        )

        response = self.client.post(
            "/admin/assets/edit",
            data={
                "action": "update",
                "lookup_asset_tag": "AT-EDIT-2",
                "asset_tag": "AT-EDIT-2",
                "serial_number": "SER-EDIT-2",
                "manufacturer": "Dell",
                "equipment_type": "laptop",
                "building": "HQ",
                "room": "111",
                "model": "Latitude",
                "model_code": "5400",
                "notes": "new return slot",
                "case_name": "CASE-D",
                "slot_id": "302",
            },
        )
        self.assertEqual(response.status_code, 302)

        asset_row = self.conn.execute(
            "SELECT location_type, current_holder_id, home_slot_id, case_number, slot_number FROM assets WHERE id = ?;",
            (asset_id,),
        ).fetchone()
        self.assertEqual(asset_row["location_type"], "IN_CUSTODY")
        self.assertEqual(asset_row["current_holder_id"], 77)
        self.assertEqual(asset_row["home_slot_id"], 302)
        self.assertEqual(asset_row["case_number"], "CASE-D")
        self.assertEqual(asset_row["slot_number"], "4")

        occ = self.conn.execute("SELECT 1 FROM slot_occupancy WHERE asset_id = ?;", (asset_id,)).fetchone()
        self.assertIsNone(occ)

    def test_edit_rejects_occupied_target_slot(self) -> None:
        self._insert_slot(401, "CASE-E", 1)
        self._insert_slot(402, "CASE-E", 2, current_asset_tag="AT-OCCUPIER")
        asset_id = self._insert_asset(
            "AT-EDIT-3",
            serial_number="SER-EDIT-3",
            location_type="STORAGE",
            current_holder_id=None,
            home_slot_id=401,
        )
        self._occupy_slot(401, asset_id, "AT-EDIT-3")
        occupier_id = self._insert_asset(
            "AT-OCCUPIER",
            serial_number="SER-OCC",
            location_type="STORAGE",
            current_holder_id=None,
            home_slot_id=402,
        )
        self._occupy_slot(402, occupier_id, "AT-OCCUPIER")

        response = self.client.post(
            "/admin/assets/edit",
            data={
                "action": "update",
                "lookup_asset_tag": "AT-EDIT-3",
                "asset_tag": "AT-EDIT-3",
                "serial_number": "SER-EDIT-3",
                "manufacturer": "Dell",
                "equipment_type": "laptop",
                "building": "HQ",
                "room": "110",
                "model": "Latitude",
                "model_code": "5400",
                "notes": "attempted move",
                "case_name": "CASE-E",
                "slot_id": "402",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"already occupied", response.data)

        asset_row = self.conn.execute("SELECT home_slot_id FROM assets WHERE id = ?;", (asset_id,)).fetchone()
        self.assertEqual(asset_row["home_slot_id"], 401)
        occ = self.conn.execute("SELECT slot_id FROM slot_occupancy WHERE asset_id = ?;", (asset_id,)).fetchone()
        self.assertEqual(occ["slot_id"], 401)


if __name__ == "__main__":
    unittest.main()
