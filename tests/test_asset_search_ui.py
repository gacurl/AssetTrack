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

    def _insert_holder(self, holder_id: int, name: str, organization: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO holders (id, holder_type, name, organization, identifier, contact_info, created_at, updated_at)
            VALUES (?, 'PERSON', ?, ?, NULL, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """,
            (holder_id, name, organization),
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
        serial_number: str,
        location_type: str,
        home_slot_id: int | None,
        current_holder_id: int | None = None,
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
            VALUES (?, ?, 'Dell', 'laptop', 'HQ', '100', 'HQ/100', 'in_stock', 'accountable', 'serviceable', '2026-01-01', '2026-01-01T00:00:00Z', ?, ?, ?);
            """,
            (asset_tag, serial_number, location_type, current_holder_id, home_slot_id),
        )
        self.conn.commit()

    def test_search_page_allows_authenticated_operator(self) -> None:
        response = self.client.get("/assets/search")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Asset Search", response.data)
        self.assertIn(b"Search by asset tag or serial number", response.data)
        self.assertNotIn(b">Clear<", response.data)

    def test_search_finds_asset_by_asset_tag(self) -> None:
        self._insert_holder(1, "Alex Holder", "Field Ops")
        self._insert_slot(10, "CASE-A", 4)
        self._insert_asset("AT-100", serial_number="SER-100", location_type="STORAGE", home_slot_id=10, current_holder_id=1)

        response = self.client.get("/assets/search?asset_tag=AT-100")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Asset Found", response.data)
        self.assertIn(b"Matched by asset tag.", response.data)
        self.assertIn(b"AT-100", response.data)
        self.assertIn(b"SER-100", response.data)
        self.assertIn(b"In storage", response.data)
        self.assertIn(b"Alex Holder (Field Ops)", response.data)
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
        self.assertIn(b"Current holder", response.data)
        self.assertIn(b"Not assigned", response.data)
        self.assertIn(b"Not assigned", response.data)

    def test_partial_asset_tag_search_returns_matching_assets(self) -> None:
        self._insert_holder(1, "Alex Holder", "Field Ops")
        self._insert_asset("AT-100", serial_number="SER-100", location_type="IN_CUSTODY", home_slot_id=None, current_holder_id=1)
        self._insert_asset("AT-101", serial_number="SER-101", location_type="STORAGE", home_slot_id=None)
        self._insert_asset("BX-200", serial_number="SER-200", location_type="STORAGE", home_slot_id=None)

        response = self.client.get("/assets/search?asset_tag=AT-10")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Assets Found", response.data)
        self.assertIn(b"2 matches shown.", response.data)
        self.assertIn(b"AT-100", response.data)
        self.assertIn(b"AT-101", response.data)
        self.assertNotIn(b"BX-200", response.data)
        self.assertIn(b"Alex Holder (Field Ops)", response.data)

    def test_partial_serial_search_returns_matching_assets(self) -> None:
        self._insert_asset("AT-200", serial_number="SER-200", location_type="IN_CUSTODY", home_slot_id=None)
        self._insert_asset("AT-201", serial_number="SER-201", location_type="STORAGE", home_slot_id=None)
        self._insert_asset("AT-999", serial_number="XYZ-999", location_type="STORAGE", home_slot_id=None)

        response = self.client.get("/assets/search?serial_number=SER-20")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Assets Found", response.data)
        self.assertIn(b"2 matches shown.", response.data)
        self.assertIn(b"AT-200", response.data)
        self.assertIn(b"AT-201", response.data)
        self.assertNotIn(b"AT-999", response.data)

    def test_combined_asset_tag_and_serial_search_uses_both_filters(self) -> None:
        self._insert_asset("AT-400", serial_number="SER-400", location_type="STORAGE", home_slot_id=None)
        self._insert_asset("AT-400X", serial_number="SER-999", location_type="STORAGE", home_slot_id=None)
        self._insert_asset("ZZ-400", serial_number="SER-400", location_type="STORAGE", home_slot_id=None)

        response = self.client.get("/assets/search?asset_tag=AT-400&serial_number=SER-400")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Asset Found", response.data)
        self.assertIn(b"AT-400", response.data)
        self.assertIn(b"SER-400", response.data)
        self.assertNotIn(b"AT-400X", response.data)
        self.assertNotIn(b"ZZ-400", response.data)

    def test_combined_partial_asset_tag_and_serial_search_stays_narrow(self) -> None:
        self._insert_asset("AT-510", serial_number="SER-510", location_type="STORAGE", home_slot_id=None)
        self._insert_asset("AT-511", serial_number="SER-777", location_type="STORAGE", home_slot_id=None)
        self._insert_asset("BT-510", serial_number="SER-510", location_type="STORAGE", home_slot_id=None)

        response = self.client.get("/assets/search?asset_tag=AT-51&serial_number=SER-51")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Asset Found", response.data)
        self.assertIn(b"AT-510", response.data)
        self.assertNotIn(b"AT-511", response.data)
        self.assertNotIn(b"BT-510", response.data)

    def test_search_shows_plain_not_found_feedback(self) -> None:
        response = self.client.get("/assets/search?asset_tag=AT-MISSING")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Asset not found.", response.data)
        self.assertNotIn(b"Asset Found", response.data)
        self.assertIn(b'href="/assets/search"', response.data)
        self.assertIn(b">Clear<", response.data)

    def test_search_page_renders_clear_link_when_any_field_is_filled(self) -> None:
        response = self.client.get("/assets/search?asset_tag=AT-100&serial_number=SER-100")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="AT-100"', response.data)
        self.assertIn(b'value="SER-100"', response.data)
        self.assertIn(b'href="/assets/search"', response.data)
        self.assertIn(b">Clear<", response.data)

    def test_clean_search_route_resets_both_fields_and_results(self) -> None:
        self._insert_asset("AT-300", serial_number="SER-300", location_type="STORAGE", home_slot_id=None)

        searched = self.client.get("/assets/search?asset_tag=AT-300&serial_number=SER-300")
        self.assertEqual(searched.status_code, 200)
        self.assertIn(b"Asset Found", searched.data)
        self.assertIn(b'value="AT-300"', searched.data)
        self.assertIn(b'value="SER-300"', searched.data)

        cleared = self.client.get("/assets/search")
        self.assertEqual(cleared.status_code, 200)
        self.assertNotIn(b"Asset Found", cleared.data)
        self.assertIn(b'value=""', cleared.data)
        self.assertNotIn(b">Clear<", cleared.data)


if __name__ == "__main__":
    unittest.main()
