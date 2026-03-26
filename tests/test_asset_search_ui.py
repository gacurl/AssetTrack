from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


class AssetSearchUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "assettrack.db"
        self.conn = db.get_connection()
        intake_app.app.testing = True
        self.client = intake_app.app.test_client()
        operator_user_id = create_test_user(username="operator", password="operator-pass", role="operator")
        login_session(self.client, operator_user_id)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

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
        serial_number: str,
        location_type: str,
        home_slot_id: int | None,
    ) -> None:
        self.conn.execute(
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
            VALUES (?, ?, 'Dell', 'laptop', 'HQ', '100', 'HQ/100', 'in_stock', 'accountable', 'serviceable', '2026-01-01', '2026-01-01T00:00:00Z', ?, NULL, ?);
            """,
            (asset_tag, serial_number, location_type, home_slot_id),
        )
        self.conn.commit()

    def test_search_page_allows_authenticated_operator(self) -> None:
        response = self.client.get("/assets/search")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Asset Search", response.data)
        self.assertIn(b"Search by asset tag or serial number", response.data)

    def test_search_finds_asset_by_asset_tag(self) -> None:
        self._insert_slot(10, "CASE-A", 4)
        self._insert_asset("AT-100", serial_number="SER-100", location_type="STORAGE", home_slot_id=10)

        response = self.client.get("/assets/search?asset_tag=AT-100")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Asset Found", response.data)
        self.assertIn(b"Matched by asset tag.", response.data)
        self.assertIn(b"AT-100", response.data)
        self.assertIn(b"SER-100", response.data)
        self.assertIn(b"In storage", response.data)
        self.assertIn(b"CASE-A", response.data)
        self.assertIn(b"Slot 4", response.data)

    def test_search_finds_asset_by_serial_number(self) -> None:
        self._insert_asset("AT-200", serial_number="SER-200", location_type="IN_CUSTODY", home_slot_id=None)

        response = self.client.get("/assets/search?serial_number=SER-200")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Asset Found", response.data)
        self.assertIn(b"Matched by serial number.", response.data)
        self.assertIn(b"AT-200", response.data)
        self.assertIn(b"SER-200", response.data)
        self.assertIn(b"In custody", response.data)
        self.assertIn(b"Not assigned", response.data)

    def test_search_shows_plain_not_found_feedback(self) -> None:
        response = self.client.get("/assets/search?asset_tag=AT-MISSING")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Asset not found.", response.data)
        self.assertNotIn(b"Asset Found", response.data)


if __name__ == "__main__":
    unittest.main()
