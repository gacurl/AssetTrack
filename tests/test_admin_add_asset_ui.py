from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.intake.scan import Scan
from tests.auth_test_utils import create_test_user, login_session


class AdminAddAssetUiTests(unittest.TestCase):
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

    def _insert_asset(self, asset_tag: str, serial_number: str) -> int:
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
            VALUES (?, ?, 'Dell', 'laptop', 'B1', '101', 'B1/101', 'in_stock', 'accountable', 'serviceable', '2026-01-01', '2026-01-01T00:00:00Z', 'STORAGE', NULL, NULL);
            """,
            (asset_tag, serial_number),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def test_get_admin_new_asset_route_allows_admin(self) -> None:
        response = self.client.get("/admin/assets/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin: Add Asset", response.data)
        self.assertIn(b"Asset type", response.data)
        self.assertIn(b'<option value="laptop"', response.data)
        self.assertIn(b'<option value="tablet"', response.data)
        self.assertIn(b'name="case_name"', response.data)
        self.assertIn(b'name="slot_id"', response.data)

    def test_add_assets_queue_renders_scan_timestamps_from_queue_items(self) -> None:
        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(
            Scan(
                asset_tag="AT-QUEUE-1",
                scanned_at=datetime(2026, 1, 1, 14, 3, 22, tzinfo=timezone.utc),
                equipment_type="laptop",
            )
        )

        response = self.client.get("/add-assets")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'14:03:22', response.data)
        self.assertIn(b'datetime="2026-01-01T14:03:22+00:00"', response.data)
        self.assertNotIn(b"localStorage.getItem", response.data)

    def test_add_assets_route_shows_case_and_slot_selectors_for_admin(self) -> None:
        self._insert_slot(110, "CASE-LIVE", 4)

        response = self.client.get("/add-assets")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="case_name"', response.data)
        self.assertIn(b'name="slot_id"', response.data)
        self.assertIn(b"CASE-LIVE", response.data)
        self.assertIn(b"Stage Asset Intake", response.data)
        self.assertIn(b"Stage in queue", response.data)
        self.assertIn(b"Review staged batch", response.data)
        self.assertIn(b"Other workflow:", response.data)
        self.assertIn(b"Return Assets", response.data)
        self.assertNotIn(b"Open batch preview", response.data)
        self.assertNotIn(b"What this does:", response.data)
        self.assertNotIn(b"How to use:", response.data)
        self.assertNotIn(b"Add to database", response.data)

    def test_add_assets_empty_scan_submission_shows_validation_message(self) -> None:
        intake_app.SCAN_QUEUE.clear()

        response = self.client.post(
            "/",
            data={"scan_text": "", "equipment_type": "tablet", "return_to": "/add-assets"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Enter or scan an asset tag before adding it to the queue.", response.data)
        self.assertEqual(len(intake_app.SCAN_QUEUE), 0)

    def test_add_assets_review_blocks_empty_queue_with_clear_message(self) -> None:
        intake_app.SCAN_QUEUE.clear()

        response = self.client.post(
            "/add-assets/review",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Queue is empty. Add at least one asset to the queue before reviewing the batch.", response.data)
        self.assertIn(b"No assets are staged yet.", response.data)

    def test_scans_keep_equipment_type_captured_at_scan_time(self) -> None:
        intake_app.SCAN_QUEUE.clear()

        first = self.client.post(
            "/",
            data={"scan_text": "AT-QUEUE-1", "equipment_type": "tablet"},
        )
        self.assertEqual(first.status_code, 302)

        second = self.client.post(
            "/",
            data={"scan_text": "AT-QUEUE-2", "equipment_type": "laptop"},
        )
        self.assertEqual(second.status_code, 302)

        self.assertEqual([scan.equipment_type for scan in intake_app.SCAN_QUEUE], ["tablet", "laptop"])

        preview = self.client.get("/preview?json=1")
        self.assertEqual(preview.status_code, 200)
        rows = preview.json["rows"]
        self.assertEqual(rows[0]["equipment_type"], "tablet")
        self.assertEqual(rows[1]["equipment_type"], "laptop")

    def test_add_assets_queue_rows_show_operator_verification_details(self) -> None:
        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(
            Scan(
                asset_tag="AT-VERIFY-1",
                scanned_at=datetime(2026, 1, 1, 14, 3, 22, tzinfo=timezone.utc),
                equipment_type="tablet",
                case_name="CASE-V",
                slot_position=3,
            )
        )
        intake_app.SCAN_QUEUE.append(
            Scan(
                asset_tag="AT-VERIFY-2",
                scanned_at=datetime(2026, 1, 1, 14, 4, 22, tzinfo=timezone.utc),
                equipment_type="laptop",
            )
        )

        response = self.client.get("/add-assets")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"AT-VERIFY-1", response.data)
        self.assertIn(b"Equipment type:</strong> tablet", response.data)
        self.assertIn(b"Case:</strong> CASE-V", response.data)
        self.assertIn(b"Slot:</strong> Slot 3", response.data)
        self.assertIn(b"AT-VERIFY-2", response.data)
        self.assertIn(b"Case:</strong> Unassigned", response.data)
        self.assertIn(b"Slot:</strong> Unassigned", response.data)

    def test_preview_shows_parsed_rows_before_confirmation_and_hides_validation_json(self) -> None:
        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(
            Scan(
                asset_tag="AT-PREVIEW-1",
                scanned_at=datetime(2026, 1, 1, 14, 5, 22, tzinfo=timezone.utc),
                equipment_type="tablet",
            )
        )

        response = self.client.get("/preview")

        self.assertEqual(response.status_code, 200)
        parsed_rows_heading = response.data.index(b"<h2>Parsed rows</h2>")
        confirmation_text = response.data.index(b"I reviewed this batch and want to add it to the database.")
        self.assertLess(parsed_rows_heading, confirmation_text)
        self.assertIn(b'action="/preview/commit"', response.data)
        self.assertIn(b'name="confirm_reviewed"', response.data)
        self.assertIn(b">Add to database<", response.data)
        self.assertNotIn(b"<h2>Validation result</h2>", response.data)
        self.assertNotIn(b"/preview/validate", response.data)

    def test_blank_equipment_type_uses_default_and_missing_field_preserves_selection(self) -> None:
        intake_app.SCAN_QUEUE.clear()

        select_tablet = self.client.post(
            "/",
            data={"scan_text": "AT-QUEUE-1", "equipment_type": "tablet"},
        )
        self.assertEqual(select_tablet.status_code, 302)

        preserve_selection = self.client.post(
            "/",
            data={"action": "clear", "return_to": "/add-assets"},
        )
        self.assertEqual(preserve_selection.status_code, 302)

        with self.client.session_transaction() as sess:
            self.assertEqual(sess["equipment_type"], "tablet")

        default_scan = self.client.post(
            "/",
            data={"scan_text": "AT-QUEUE-2", "equipment_type": ""},
        )
        self.assertEqual(default_scan.status_code, 302)
        self.assertEqual(len(intake_app.SCAN_QUEUE), 1)
        self.assertEqual(intake_app.SCAN_QUEUE[0].equipment_type, "laptop")

        with self.client.session_transaction() as sess:
            self.assertEqual(sess["equipment_type"], "laptop")

    def test_post_creates_unslotted_asset_and_enforces_serial_uniqueness(self) -> None:
        response = self.client.post(
            "/admin/assets/new",
            data={
                "asset_tag": "AT-500",
                "serial_number": "SER-500",
                "manufacturer": "Lenovo",
                "equipment_type": "laptop",
                "building": "HQ",
                "room": "120",
                "model": "T14",
                "model_code": "GEN5",
                "notes": "new intake",
            },
        )
        self.assertEqual(response.status_code, 302)

        asset_row = self.conn.execute(
            """
            SELECT asset_tag, serial_number, manufacturer, location_type, current_holder_id, home_slot_id
            FROM assets
            WHERE asset_tag = ?;
            """,
            ("AT-500",),
        ).fetchone()
        self.assertIsNotNone(asset_row)
        self.assertEqual(asset_row["serial_number"], "SER-500")
        self.assertEqual(asset_row["manufacturer"], "Lenovo")
        self.assertEqual(asset_row["location_type"], "STORAGE")
        self.assertIsNone(asset_row["current_holder_id"])
        self.assertIsNone(asset_row["home_slot_id"])

        duplicate = self.client.post(
            "/admin/assets/new",
            data={
                "asset_tag": "AT-501",
                "serial_number": "SER-500",
                "manufacturer": "Lenovo",
                "equipment_type": "laptop",
                "building": "HQ",
                "room": "121",
            },
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertIn(b"Serial number already exists.", duplicate.data)
        missing = self.conn.execute("SELECT 1 FROM assets WHERE asset_tag = ?;", ("AT-501",)).fetchone()
        self.assertIsNone(missing)

    def test_post_creates_slotted_asset_by_case_and_slot_and_writes_both_events(self) -> None:
        self._insert_slot(101, "CASE-A", 7)

        response = self.client.post(
            "/admin/assets/new",
            data={
                "asset_tag": "AT-600",
                "serial_number": "SER-600",
                "manufacturer": "HP",
                "equipment_type": "tablet",
                "building": "HQ",
                "room": "220",
                "case_name": "CASE-A",
                "slot_id": "101",
            },
        )
        self.assertEqual(response.status_code, 302)

        asset_row = self.conn.execute(
            "SELECT id, home_slot_id FROM assets WHERE asset_tag = ?;",
            ("AT-600",),
        ).fetchone()
        self.assertIsNotNone(asset_row)
        self.assertEqual(asset_row["home_slot_id"], 101)

        occ = self.conn.execute(
            "SELECT slot_id FROM slot_occupancy WHERE asset_id = ?;",
            (asset_row["id"],),
        ).fetchone()
        self.assertIsNotNone(occ)
        self.assertEqual(occ["slot_id"], 101)

        slot = self.conn.execute("SELECT current_asset_tag FROM slots WHERE id = 101;").fetchone()
        self.assertEqual(slot["current_asset_tag"], "AT-600")

        events = self.conn.execute(
            """
            SELECT event_type
            FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id ASC;
            """,
            ("AT-600",),
        ).fetchall()
        self.assertEqual([row["event_type"] for row in events], ["ASSET_CREATED", "SLOT_ASSIGN"])

    def test_post_duplicate_serial_number_rejected_with_rollback(self) -> None:
        self._insert_asset("AT-700", "SER-DUP")
        self._insert_slot(102, "CASE-B", 1)

        response = self.client.post(
            "/admin/assets/new",
            data={
                "asset_tag": "AT-701",
                "serial_number": "SER-DUP",
                "manufacturer": "Dell",
                "equipment_type": "laptop",
                "building": "HQ",
                "room": "330",
                "case_name": "CASE-B",
                "slot_id": "102",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Serial number already exists.", response.data)

        created = self.conn.execute("SELECT 1 FROM assets WHERE asset_tag = ?;", ("AT-701",)).fetchone()
        self.assertIsNone(created)
        slot = self.conn.execute("SELECT current_asset_tag FROM slots WHERE id = 102;").fetchone()
        self.assertIsNone(slot["current_asset_tag"])

    def test_post_invalid_submission_returns_plain_language_feedback(self) -> None:
        self._insert_slot(140, "CASE-D", 2)

        response = self.client.post(
            "/admin/assets/new",
            data={
                "asset_tag": "",
                "serial_number": "",
                "manufacturer": "",
                "equipment_type": "printer",
                "building": "",
                "room": "",
                "case_name": "CASE-D",
                "slot_id": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Enter an asset tag.", response.data)
        self.assertIn(b"Enter a serial number.", response.data)
        self.assertIn(b"Enter a manufacturer.", response.data)
        self.assertIn(b"Choose a valid asset type.", response.data)
        self.assertIn(b"Enter the building.", response.data)
        self.assertIn(b"Enter the room.", response.data)
        self.assertIn(b"Choose both a case and a slot, or leave both blank.", response.data)
        self.assertNotIn(b"asset_tag is required", response.data)
        self.assertNotIn(b"serial_number is required", response.data)

    def test_post_assign_now_with_occupied_slot_rejected_with_rollback(self) -> None:
        existing_id = self._insert_asset("AT-800", "SER-800")
        self._insert_slot(103, "CASE-C", 9, current_asset_tag="AT-800")
        self.conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (103, ?, '2026-01-02T00:00:00Z');
            """,
            (existing_id,),
        )
        self.conn.commit()

        response = self.client.post(
            "/admin/assets/new",
            data={
                "asset_tag": "AT-801",
                "serial_number": "SER-801",
                "manufacturer": "Dell",
                "equipment_type": "laptop",
                "building": "HQ",
                "room": "331",
                "case_name": "CASE-C",
                "slot_id": "103",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"already occupied", response.data)

        created = self.conn.execute("SELECT 1 FROM assets WHERE asset_tag = ?;", ("AT-801",)).fetchone()
        self.assertIsNone(created)
        event = self.conn.execute("SELECT 1 FROM asset_events WHERE asset_tag = ?;", ("AT-801",)).fetchone()
        self.assertIsNone(event)

    def test_add_assets_live_seam_commits_new_asset_with_selected_slot(self) -> None:
        self._insert_slot(120, "CASE-Q", 5)
        stored_tag = "ATLIVE1"

        queued = self.client.post(
            "/",
            data={
                "scan_text": "AT-LIVE-1",
                "equipment_type": "tablet",
                "case_name": "CASE-Q",
                "slot_id": "120",
                "return_to": "/add-assets",
            },
        )
        self.assertEqual(queued.status_code, 302)
        self.assertEqual(len(intake_app.SCAN_QUEUE), 1)
        self.assertEqual(intake_app.SCAN_QUEUE[0].asset_tag, stored_tag)
        self.assertEqual(intake_app.SCAN_QUEUE[0].home_slot_id, 120)
        self.assertEqual(intake_app.SCAN_QUEUE[0].case_name, "CASE-Q")
        self.assertEqual(intake_app.SCAN_QUEUE[0].slot_position, 5)

        committed = self.client.post(
            "/preview/commit",
            data={"confirm_reviewed": "on"},
            follow_redirects=True,
        )
        self.assertEqual(committed.status_code, 200)
        self.assertIn(b"Added 1 item to the database.", committed.data)

        verify_conn = db.get_connection()
        try:
            asset_row = verify_conn.execute(
                """
                SELECT asset_tag, equipment_type, location_type, current_holder_id, home_slot_id
                FROM assets
                WHERE asset_tag = ?;
                """,
                (stored_tag,),
            ).fetchone()
            self.assertIsNotNone(asset_row)
            self.assertEqual(asset_row["asset_tag"], stored_tag)
            self.assertEqual(asset_row["equipment_type"], "tablet")
            self.assertEqual(asset_row["location_type"], "STORAGE")
            self.assertIsNone(asset_row["current_holder_id"])
            self.assertEqual(asset_row["home_slot_id"], 120)

            occ = verify_conn.execute(
                "SELECT slot_id FROM slot_occupancy WHERE asset_id = (SELECT id FROM assets WHERE asset_tag = ?);",
                (stored_tag,),
            ).fetchone()
            self.assertIsNotNone(occ)
            self.assertEqual(occ["slot_id"], 120)

            slot = verify_conn.execute("SELECT current_asset_tag FROM slots WHERE id = 120;").fetchone()
            self.assertEqual(slot["current_asset_tag"], stored_tag)
        finally:
            verify_conn.close()

    def test_add_assets_live_seam_rejects_occupied_slot_on_commit(self) -> None:
        existing_id = self._insert_asset("AT-OCC-LIVE", "SER-OCC-LIVE")
        self._insert_slot(130, "CASE-O", 8, current_asset_tag="AT-OCC-LIVE")
        stored_tag = "ATLIVE2"
        self.conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (130, ?, '2026-01-02T00:00:00Z');
            """,
            (existing_id,),
        )
        self.conn.commit()

        queued = self.client.post(
            "/",
            data={
                "scan_text": "AT-LIVE-2",
                "equipment_type": "laptop",
                "case_name": "CASE-O",
                "slot_id": "130",
                "return_to": "/add-assets",
            },
        )
        self.assertEqual(queued.status_code, 302)

        blocked = self.client.post(
            "/preview/commit",
            data={"confirm_reviewed": "on"},
            follow_redirects=True,
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertIn(b"Selected slot is already occupied", blocked.data)

        verify_conn = db.get_connection()
        try:
            created = verify_conn.execute("SELECT 1 FROM assets WHERE asset_tag = ?;", (stored_tag,)).fetchone()
            self.assertIsNone(created)
        finally:
            verify_conn.close()


if __name__ == "__main__":
    unittest.main()
