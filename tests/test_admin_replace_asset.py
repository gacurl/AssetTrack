from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


class AdminReplaceAssetTests(unittest.TestCase):
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
                model_code TEXT NULL,
                notes TEXT NULL,
                building_room TEXT NULL,
                equipment_type TEXT NOT NULL,
                custody_state TEXT NULL,
                accountability_status TEXT NULL,
                condition TEXT NULL,
                created_date TEXT NULL,
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
        admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
        login_session(self.client, admin_user_id)

    def tearDown(self) -> None:
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
        serial_number: str,
        location_type: str,
        holder_id: int | None = None,
        home_slot_id: int | None = None,
        building_room: str = "HQ/100",
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO assets (
                asset_tag,
                serial_number,
                manufacturer,
                model,
                model_code,
                notes,
                building_room,
                equipment_type,
                custody_state,
                accountability_status,
                condition,
                created_date,
                updated_date,
                location_type,
                current_holder_id,
                home_slot_id
            )
            VALUES (
                ?, ?, 'Dell', 'Latitude', 'LAT', NULL, ?, 'laptop',
                'in_stock', 'accountable', 'serviceable', '2026-01-01', '2026-01-01T00:00:00Z',
                ?, ?, ?
            );
            """,
            (asset_tag, serial_number, building_room, location_type, holder_id, home_slot_id),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def _assign_slot(self, slot_id: int, asset_id: int, asset_tag: str) -> None:
        self.conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (?, ?, '2026-02-01T00:00:00Z');
            """,
            (slot_id, asset_id),
        )
        self.conn.execute("UPDATE slots SET current_asset_tag = ? WHERE id = ?;", (asset_tag, slot_id))
        self.conn.commit()

    def test_get_replace_route_allows_admin(self) -> None:
        response = self.client.get("/admin/assets/replace")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin: Replace Failed Asset", response.data)

    def test_loaded_replace_form_offers_only_supported_replacement_types(self) -> None:
        self._insert_slot(9, "CASE-TYPES", 1, None)
        failed_id = self._insert_asset(
            "FAIL-TYPES",
            serial_number="SER-FAIL-TYPES",
            location_type="STORAGE",
            holder_id=None,
            home_slot_id=9,
        )
        self._assign_slot(9, failed_id, "FAIL-TYPES")

        response = self.client.post(
            "/admin/assets/replace",
            data={"action": "lookup", "failed_asset_tag": "FAIL-TYPES"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<option value="laptop"', response.data)
        self.assertIn(b'<option value="switch"', response.data)
        self.assertIn(b'<option value="router"', response.data)
        self.assertNotIn(b'<option value="monitor"', response.data)

    def test_swap_from_storage_success(self) -> None:
        self._insert_slot(10, "CASE-A", 1, None)
        failed_id = self._insert_asset(
            "FAIL-100",
            serial_number="SER-FAIL-100",
            location_type="STORAGE",
            holder_id=None,
            home_slot_id=10,
        )
        self._assign_slot(10, failed_id, "FAIL-100")

        response = self.client.post(
            "/admin/assets/replace",
            data={
                "action": "replace",
                "failed_asset_tag": "FAIL-100",
                "failure_type": "HARDWARE",
                "failure_notes": "Power rail damage.",
                "replacement_asset_tag": "NEW-100",
                "replacement_serial_number": "SER-NEW-100",
                "replacement_manufacturer": "Lenovo",
                "replacement_equipment_type": "laptop",
                "replacement_model": "T14",
                "replacement_model_code": "G5",
                "replacement_notes": "swap replacement",
                "confirm_retire": "yes",
                "confirm_slot": "yes",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Replaced FAIL-100 with NEW-100", response.data)

        failed = self.conn.execute(
            "SELECT location_type, current_holder_id, home_slot_id FROM assets WHERE id = ?;",
            (failed_id,),
        ).fetchone()
        self.assertEqual(failed["location_type"], "DISPOSED")
        self.assertIsNone(failed["current_holder_id"])
        self.assertIsNone(failed["home_slot_id"])

        replacement = self.conn.execute(
            """
            SELECT id, location_type, current_holder_id, home_slot_id
            FROM assets
            WHERE asset_tag = ?;
            """,
            ("NEW-100",),
        ).fetchone()
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement["location_type"], "STORAGE")
        self.assertIsNone(replacement["current_holder_id"])
        self.assertEqual(replacement["home_slot_id"], 10)

        slot_occ = self.conn.execute(
            "SELECT asset_id FROM slot_occupancy WHERE slot_id = 10;",
        ).fetchone()
        self.assertEqual(slot_occ["asset_id"], replacement["id"])
        slot = self.conn.execute("SELECT current_asset_tag FROM slots WHERE id = 10;").fetchone()
        self.assertEqual(slot["current_asset_tag"], "NEW-100")

        failed_event = self.conn.execute(
            """
            SELECT event_type
            FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            ("FAIL-100",),
        ).fetchone()
        self.assertEqual(failed_event["event_type"], "ASSET_RETIRED")

        replacement_events = self.conn.execute(
            """
            SELECT event_type
            FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id ASC;
            """,
            ("NEW-100",),
        ).fetchall()
        self.assertEqual([row["event_type"] for row in replacement_events], ["ASSET_CREATED", "SLOT_ASSIGN"])

    def test_swap_from_in_custody_success(self) -> None:
        self._insert_slot(11, "CASE-B", 2, None)
        failed_id = self._insert_asset(
            "FAIL-200",
            serial_number="SER-FAIL-200",
            location_type="IN_CUSTODY",
            holder_id=99,
            home_slot_id=11,
        )

        response = self.client.post(
            "/admin/assets/replace",
            data={
                "action": "replace",
                "failed_asset_tag": "FAIL-200",
                "failure_type": "LOST",
                "failure_notes": "Lost in field operations.",
                "replacement_asset_tag": "NEW-200",
                "replacement_serial_number": "SER-NEW-200",
                "replacement_manufacturer": "HP",
                "replacement_equipment_type": "laptop",
                "confirm_retire": "yes",
                "confirm_slot": "yes",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        failed = self.conn.execute(
            "SELECT location_type, current_holder_id, home_slot_id FROM assets WHERE id = ?;",
            (failed_id,),
        ).fetchone()
        self.assertEqual(failed["location_type"], "DISPOSED")
        self.assertIsNone(failed["current_holder_id"])
        self.assertIsNone(failed["home_slot_id"])

        replacement = self.conn.execute(
            "SELECT location_type, home_slot_id FROM assets WHERE asset_tag = ?;",
            ("NEW-200",),
        ).fetchone()
        self.assertEqual(replacement["location_type"], "STORAGE")
        self.assertEqual(replacement["home_slot_id"], 11)

        retired_event = self.conn.execute(
            """
            SELECT event_type, holder_id
            FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            ("FAIL-200",),
        ).fetchone()
        self.assertEqual(retired_event["event_type"], "ASSET_RETIRED_IN_FIELD")
        self.assertEqual(retired_event["holder_id"], 99)

    def test_missing_target_slot_is_blocked(self) -> None:
        self._insert_asset(
            "FAIL-300",
            serial_number="SER-FAIL-300",
            location_type="STORAGE",
            holder_id=None,
            home_slot_id=None,
        )

        response = self.client.post(
            "/admin/assets/replace",
            data={
                "action": "replace",
                "failed_asset_tag": "FAIL-300",
                "failure_type": "HARDWARE",
                "failure_notes": "Broken.",
                "replacement_asset_tag": "NEW-300",
                "replacement_serial_number": "SER-NEW-300",
                "replacement_manufacturer": "Lenovo",
                "replacement_equipment_type": "laptop",
                "confirm_retire": "yes",
                "confirm_slot": "yes",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Asset has no slot. Assign a slot first.", response.data)

        replacement = self.conn.execute("SELECT 1 FROM assets WHERE asset_tag = 'NEW-300';").fetchone()
        self.assertIsNone(replacement)

    def test_target_slot_occupied_by_other_asset_is_blocked_with_no_partial_updates(self) -> None:
        self._insert_slot(12, "CASE-C", 3, None)
        failed_id = self._insert_asset(
            "FAIL-400",
            serial_number="SER-FAIL-400",
            location_type="STORAGE",
            holder_id=None,
            home_slot_id=12,
        )
        other_id = self._insert_asset(
            "OTHER-400",
            serial_number="SER-OTHER-400",
            location_type="STORAGE",
            holder_id=None,
            home_slot_id=12,
        )
        self._assign_slot(12, other_id, "OTHER-400")

        response = self.client.post(
            "/admin/assets/replace",
            data={
                "action": "replace",
                "failed_asset_tag": "FAIL-400",
                "failure_type": "HARDWARE",
                "failure_notes": "Broken.",
                "replacement_asset_tag": "NEW-400",
                "replacement_serial_number": "SER-NEW-400",
                "replacement_manufacturer": "Lenovo",
                "replacement_equipment_type": "laptop",
                "confirm_retire": "yes",
                "confirm_slot": "yes",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Target slot is occupied by another asset.", response.data)

        failed = self.conn.execute(
            "SELECT location_type, home_slot_id FROM assets WHERE id = ?;",
            (failed_id,),
        ).fetchone()
        self.assertEqual(failed["location_type"], "STORAGE")
        self.assertEqual(failed["home_slot_id"], 12)
        replacement = self.conn.execute("SELECT 1 FROM assets WHERE asset_tag = 'NEW-400';").fetchone()
        self.assertIsNone(replacement)

    def test_duplicate_replacement_identifiers_are_blocked(self) -> None:
        self._insert_slot(13, "CASE-D", 4, None)
        failed_id = self._insert_asset(
            "FAIL-500",
            serial_number="SER-FAIL-500",
            location_type="STORAGE",
            holder_id=None,
            home_slot_id=13,
        )
        self._assign_slot(13, failed_id, "FAIL-500")
        self._insert_asset(
            "EXISTING-TAG",
            serial_number="SER-EXISTING",
            location_type="STORAGE",
            holder_id=None,
            home_slot_id=None,
        )

        duplicate_tag = self.client.post(
            "/admin/assets/replace",
            data={
                "action": "replace",
                "failed_asset_tag": "FAIL-500",
                "failure_type": "HARDWARE",
                "failure_notes": "Broken.",
                "replacement_asset_tag": "EXISTING-TAG",
                "replacement_serial_number": "SER-NEW-500",
                "replacement_manufacturer": "Lenovo",
                "replacement_equipment_type": "laptop",
                "confirm_retire": "yes",
                "confirm_slot": "yes",
            },
        )
        self.assertEqual(duplicate_tag.status_code, 200)
        self.assertIn(b"replacement asset_tag already exists.", duplicate_tag.data)

        duplicate_serial = self.client.post(
            "/admin/assets/replace",
            data={
                "action": "replace",
                "failed_asset_tag": "FAIL-500",
                "failure_type": "HARDWARE",
                "failure_notes": "Broken.",
                "replacement_asset_tag": "NEW-500",
                "replacement_serial_number": "SER-EXISTING",
                "replacement_manufacturer": "Lenovo",
                "replacement_equipment_type": "laptop",
                "confirm_retire": "yes",
                "confirm_slot": "yes",
            },
        )
        self.assertEqual(duplicate_serial.status_code, 200)
        self.assertIn(b"replacement serial_number already exists.", duplicate_serial.data)

        failed = self.conn.execute(
            "SELECT location_type, home_slot_id FROM assets WHERE asset_tag = 'FAIL-500';",
        ).fetchone()
        self.assertEqual(failed["location_type"], "STORAGE")
        self.assertEqual(failed["home_slot_id"], 13)
        replacement = self.conn.execute("SELECT 1 FROM assets WHERE asset_tag = 'NEW-500';").fetchone()
        self.assertIsNone(replacement)

    def test_unsupported_replacement_equipment_type_is_rejected_without_partial_updates(self) -> None:
        self._insert_slot(14, "CASE-E", 5, None)
        failed_id = self._insert_asset(
            "FAIL-600",
            serial_number="SER-FAIL-600",
            location_type="STORAGE",
            holder_id=None,
            home_slot_id=14,
        )
        self._assign_slot(14, failed_id, "FAIL-600")

        response = self.client.post(
            "/admin/assets/replace",
            data={
                "action": "replace",
                "failed_asset_tag": "FAIL-600",
                "failure_type": "HARDWARE",
                "failure_notes": "Broken.",
                "replacement_asset_tag": "NEW-600",
                "replacement_serial_number": "SER-NEW-600",
                "replacement_manufacturer": "Lenovo",
                "replacement_equipment_type": "monitor",
                "confirm_retire": "yes",
                "confirm_slot": "yes",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Supported asset types are Laptop, Switch, and Router.", response.data)
        failed = self.conn.execute(
            "SELECT location_type, home_slot_id FROM assets WHERE id = ?;",
            (failed_id,),
        ).fetchone()
        self.assertEqual(failed["location_type"], "STORAGE")
        self.assertEqual(failed["home_slot_id"], 14)
        replacement = self.conn.execute("SELECT 1 FROM assets WHERE asset_tag = 'NEW-600';").fetchone()
        self.assertIsNone(replacement)


if __name__ == "__main__":
    unittest.main()
