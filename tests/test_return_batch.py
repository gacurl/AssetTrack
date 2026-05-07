# file: tests/test_return_batch.py
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


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
        operator_user_id = create_test_user(username="operator", password="op-pass", role="operator")
        login_session(self.client, operator_user_id)

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

    def _insert_holder(self, holder_id: int, name: str, email: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO holders (
                id, holder_type, name, identifier, email, contact_info, created_at, updated_at
            )
            VALUES (?, 'PERSON', ?, ?, ?, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """,
            (holder_id, name, f"H-{holder_id}", email),
        )
        self.conn.commit()

    def test_return_preview_and_commit_gating(self) -> None:
        self._insert_holder(5, "Return Holder Five")
        self._insert_holder(9, "Return Holder Nine", email="return@example.org")
        self._insert_slot(10, "A", 1, None)
        self._insert_slot(20, "B", 2, None)
        self._insert_asset("TAG-VALID", location_type="IN_CUSTODY", holder_id=5, home_slot_id=10)
        self._insert_asset("TAG-OK", location_type="IN_CUSTODY", holder_id=9, home_slot_id=20)

        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="TAG-VALID", equipment_type="laptop"))

        render = self.client.get("/return")
        self.assertEqual(render.status_code, 200)
        self.assertIn(b"Return Assets", render.data)
        self.assertIn(b"Returning Assets", render.data)
        self.assertIn(b"Home location: Home slots", render.data)
        self.assertIn(b"1 asset queued", render.data)

        preview_render = self.client.get("/return/preview")
        self.assertEqual(preview_render.status_code, 200)
        self.assertIn("Return Assets — Preview / Confirm".encode("utf-8"), preview_render.data)
        self.assertIn(b"Confirm Return", preview_render.data)
        self.assertIn(b"Confirm This Return Batch", preview_render.data)
        self.assertIn(b"Home location: Home slots", preview_render.data)
        self.assertIn(b"1 asset queued", preview_render.data)
        self.assertIn(b"Current State", preview_render.data)
        self.assertIn(b"After Return", preview_render.data)
        self.assertIn(b"Location: IN_CUSTODY", preview_render.data)
        self.assertIn(b"Issued to: Return Holder Five", preview_render.data)
        self.assertIn(b"Home location: A / 1", preview_render.data)
        self.assertIn(b'name="confirm_responsibility_ack"', preview_render.data)
        self.assertIn(b"responsibility for this return batch was acknowledged before commit", preview_render.data)
        self.assertNotIn(b"null", preview_render.data)

        unreviewed = self.client.post("/return/commit?json=1")
        self.assertEqual(unreviewed.status_code, 400)
        self.assertFalse(unreviewed.json["ok"])
        self.assertEqual(unreviewed.json["committed"], 0)
        self.assertEqual(
            unreviewed.json["error"],
            "Please confirm you reviewed the batch before returning assets.",
        )

        missing_ack = self.client.post(
            "/return/commit?json=1",
            data={"confirm_reviewed": "on"},
        )
        self.assertEqual(missing_ack.status_code, 400)
        self.assertFalse(missing_ack.json["ok"])
        self.assertEqual(missing_ack.json["committed"], 0)
        self.assertEqual(
            missing_ack.json["error"],
            "Confirm responsibility acknowledgment before returning assets.",
        )

        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="TAG-VALID", equipment_type="laptop"))
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="UNKNOWN", equipment_type="laptop"))

        blocked = self.client.post(
            "/return/commit?json=1",
            data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        )
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

        success = self.client.post(
            "/return/commit?json=1",
            data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        )
        self.assertEqual(success.status_code, 200)
        self.assertTrue(success.json["ok"])
        self.assertEqual(success.json["committed"], 1)
        self.assertIsInstance(success.json["receipt_id"], int)
        self.assertEqual(success.json["error"], None)
        self.assertEqual(len(intake_app.SCAN_QUEUE), 0)

        asset_after = self.conn.execute(
            "SELECT location_type, current_holder_id FROM assets WHERE asset_tag = ?;",
            ("TAG-OK",),
        ).fetchone()
        self.assertEqual(asset_after["location_type"], "STORAGE")
        self.assertIsNone(asset_after["current_holder_id"])

        occupancy_after = self.conn.execute(
            """
            SELECT slot_id
            FROM slot_occupancy
            WHERE asset_id = (SELECT id FROM assets WHERE asset_tag = ?)
            LIMIT 1;
            """,
            ("TAG-OK",),
        ).fetchone()
        self.assertIsNotNone(occupancy_after)
        self.assertEqual(int(occupancy_after["slot_id"]), 20)

        slot_after = self.conn.execute(
            "SELECT current_asset_tag FROM slots WHERE id = ?;",
            (20,),
        ).fetchone()
        self.assertEqual(slot_after["current_asset_tag"], "TAG-OK")

        event_row = self.conn.execute(
            """
            SELECT id, event_type, payload FROM asset_events
            WHERE asset_tag = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            ("TAG-OK",),
        ).fetchone()
        receipt_row = self.conn.execute(
            """
            SELECT receipt_type, commit_operator_user_id, holder_id, source_event_ids_json, snapshot_json, sent_at, last_attempt_at, last_error
            FROM receipt_queue
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()
        self.assertIsNotNone(event_row)
        self.assertEqual(event_row["event_type"], "RETURN")
        payload = json.loads(str(event_row["payload"]))
        self.assertEqual(payload["from_location_type"], "IN_CUSTODY")
        self.assertEqual(payload["to_location_type"], "STORAGE")
        self.assertEqual(int(payload["home_slot_id"]), 20)
        self.assertTrue(payload["responsibility_ack"]["acknowledged"])
        self.assertEqual(int(payload["responsibility_ack"]["ack_holder_id"]), 9)
        self.assertGreater(int(payload["responsibility_ack"]["ack_operator_user_id"]), 0)
        self.assertTrue(payload["responsibility_ack"]["ack_at"])
        self.assertEqual(payload["responsibility_ack"]["ack_scope"], "batch")
        self.assertIsNotNone(receipt_row)
        self.assertEqual(receipt_row["receipt_type"], "RETURN")
        self.assertGreater(int(receipt_row["commit_operator_user_id"]), 0)
        self.assertEqual(int(receipt_row["holder_id"]), 9)
        self.assertEqual(json.loads(str(receipt_row["source_event_ids_json"])), [int(event_row["id"])])
        receipt_snapshot = json.loads(str(receipt_row["snapshot_json"]))
        self.assertEqual(receipt_snapshot["receipt_type"], "RETURN")
        self.assertEqual(receipt_snapshot["holder_id"], 9)
        self.assertEqual(receipt_snapshot["source_event_ids"], [int(event_row["id"])])
        self.assertEqual(receipt_snapshot["delivery"]["state"], "pending")
        self.assertEqual(receipt_snapshot["recipient_email"], "return@example.org")
        self.assertEqual(receipt_snapshot["holder_snapshot"]["email"], "return@example.org")
        self.assertEqual(len(receipt_snapshot["assets"]), 1)
        self.assertEqual(receipt_snapshot["assets"][0]["asset_tag"], "TAG-OK")
        self.assertEqual(receipt_snapshot["assets"][0]["from_holder_snapshot"]["email"], "return@example.org")
        self.assertEqual(receipt_snapshot["assets"][0]["from_location_type"], "IN_CUSTODY")
        self.assertEqual(receipt_snapshot["assets"][0]["to_location_type"], "STORAGE")
        self.assertIsNone(receipt_row["sent_at"])
        self.assertIsNone(receipt_row["last_attempt_at"])
        self.assertIsNone(receipt_row["last_error"])

    def test_return_commit_restores_slot_occupancy_after_issue_path_removal(self) -> None:
        self._insert_holder(5, "Return Holder Five")
        self._insert_slot(55, "CASE-55", 5, None)
        self._insert_asset("TAG-RESTORE", location_type="IN_CUSTODY", holder_id=5, home_slot_id=55)

        asset_id = int(
            self.conn.execute(
                "SELECT id FROM assets WHERE asset_tag = ? LIMIT 1;",
                ("TAG-RESTORE",),
            ).fetchone()[0]
        )

        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM slot_occupancy WHERE asset_id = ? LIMIT 1;",
                (asset_id,),
            ).fetchone()
        )

        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="TAG-RESTORE", equipment_type="laptop"))

        success = self.client.post(
            "/return/commit?json=1",
            data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        )

        self.assertEqual(success.status_code, 200)
        self.assertTrue(success.json["ok"])

        occupancy_after = self.conn.execute(
            "SELECT slot_id FROM slot_occupancy WHERE asset_id = ? LIMIT 1;",
            (asset_id,),
        ).fetchone()
        self.assertIsNotNone(occupancy_after)
        self.assertEqual(int(occupancy_after["slot_id"]), 55)

        slot_after = self.conn.execute(
            "SELECT current_asset_tag FROM slots WHERE id = 55 LIMIT 1;"
        ).fetchone()
        self.assertIsNotNone(slot_after)
        self.assertEqual(str(slot_after["current_asset_tag"]), "TAG-RESTORE")

    def test_return_commit_with_mixed_holders_keeps_snapshot_email_blank(self) -> None:
        self._insert_holder(5, "Return Holder Five", email="five@example.org")
        self._insert_holder(9, "Return Holder Nine", email="nine@example.org")
        self._insert_slot(10, "A", 1, None)
        self._insert_slot(20, "B", 2, None)
        self._insert_asset("TAG-ONE", location_type="IN_CUSTODY", holder_id=5, home_slot_id=10)
        self._insert_asset("TAG-TWO", location_type="IN_CUSTODY", holder_id=9, home_slot_id=20)

        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="TAG-ONE", equipment_type="laptop"))
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="TAG-TWO", equipment_type="laptop"))

        success = self.client.post(
            "/return/commit?json=1",
            data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        )

        self.assertEqual(success.status_code, 200)

        receipt_row = self.conn.execute(
            """
            SELECT holder_id, snapshot_json
            FROM receipt_queue
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()
        self.assertIsNotNone(receipt_row)
        self.assertIsNone(receipt_row["holder_id"])
        receipt_snapshot = json.loads(str(receipt_row["snapshot_json"]))
        self.assertIsNone(receipt_snapshot["holder_id"])
        self.assertEqual(receipt_snapshot["recipient_email"], "")

    def test_return_commit_missing_ack_redirects_back_to_preview_with_message(self) -> None:
        self._insert_slot(21, "C", 3, None)
        self._insert_asset("TAG-MSG", location_type="IN_CUSTODY", holder_id=11, home_slot_id=21)

        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="TAG-MSG", equipment_type="laptop"))

        blocked = self.client.post(
            "/return/commit",
            data={"confirm_reviewed": "on"},
            follow_redirects=False,
        )

        self.assertEqual(blocked.status_code, 302)
        self.assertTrue((blocked.headers.get("Location") or "").endswith("/return/preview"))

        follow = self.client.get("/return/preview")
        self.assertEqual(follow.status_code, 200)
        self.assertIn(b"Confirm responsibility acknowledgment before returning assets.", follow.data)
        self.assertEqual(len(intake_app.SCAN_QUEUE), 1)
        receipt_count = self.conn.execute("SELECT COUNT(*) AS c FROM receipt_queue;").fetchone()
        self.assertEqual(int(receipt_count["c"]), 0)

    def test_single_asset_return_success_message_shows_final_location(self) -> None:
        self._insert_slot(30, "CASE-13", 6, None)
        self._insert_asset("MVPLAPTOP02", location_type="IN_CUSTODY", holder_id=7, home_slot_id=30)

        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="MVPLAPTOP02", equipment_type="laptop"))

        response = self.client.post(
            "/return/commit",
            data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Return Receipt", response.data)
        self.assertIn(b"MVPLAPTOP02", response.data)
        self.assertIn(b"CASE-13 / 6", response.data)

        asset_after = self.conn.execute(
            "SELECT location_type, current_holder_id FROM assets WHERE asset_tag = ?;",
            ("MVPLAPTOP02",),
        ).fetchone()
        self.assertIsNotNone(asset_after)
        self.assertEqual(asset_after["location_type"], "STORAGE")
        self.assertIsNone(asset_after["current_holder_id"])

    def test_return_commit_redirects_to_exact_created_receipt(self) -> None:
        self._insert_slot(31, "CASE-14", 2, None)
        self._insert_asset("RETURN-REDIRECT", location_type="IN_CUSTODY", holder_id=12, home_slot_id=31)

        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="RETURN-REDIRECT", equipment_type="laptop"))

        response = self.client.post(
            "/return/commit",
            data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        receipt_row = self.conn.execute(
            "SELECT id FROM receipt_queue ORDER BY id DESC LIMIT 1;"
        ).fetchone()
        self.assertIsNotNone(receipt_row)
        self.assertTrue((response.headers.get("Location") or "").endswith(f"/receipts/{int(receipt_row['id'])}"))

    def test_multi_asset_return_same_case_shows_one_case_drilldown_link(self) -> None:
        self._insert_slot(40, "CASE-SAME", 1, None)
        self._insert_slot(41, "CASE-SAME", 2, None)
        self._insert_asset("SAME-1", location_type="IN_CUSTODY", holder_id=7, home_slot_id=40)
        self._insert_asset("SAME-2", location_type="IN_CUSTODY", holder_id=8, home_slot_id=41)

        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="SAME-1", equipment_type="laptop"))
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="SAME-2", equipment_type="laptop"))

        response = self.client.post(
            "/return/commit",
            data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Return Receipt", response.data)
        self.assertIn(b"SAME-1", response.data)
        self.assertIn(b"SAME-2", response.data)

    def test_multi_asset_return_different_cases_shows_one_link_per_case(self) -> None:
        self._insert_slot(50, "CASE-X", 1, None)
        self._insert_slot(60, "CASE-Y", 1, None)
        self._insert_asset("DIFF-1", location_type="IN_CUSTODY", holder_id=7, home_slot_id=50)
        self._insert_asset("DIFF-2", location_type="IN_CUSTODY", holder_id=8, home_slot_id=60)

        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="DIFF-1", equipment_type="laptop"))
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="DIFF-2", equipment_type="laptop"))

        response = self.client.post(
            "/return/commit",
            data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Return Receipt", response.data)
        self.assertIn(b"DIFF-1", response.data)
        self.assertIn(b"DIFF-2", response.data)

    def test_return_queue_can_remove_one_item_and_preview_only_remaining_items(self) -> None:
        intake_app.SCAN_QUEUE.clear()
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="REMOVE-ME", equipment_type="laptop"))
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="KEEP-ME", equipment_type="laptop"))

        remove = self.client.post(
            "/",
            data={"action": "remove", "queue_index": "0", "return_to": "/return"},
            follow_redirects=True,
        )

        self.assertEqual(remove.status_code, 200)
        self.assertEqual([scan.asset_tag for scan in intake_app.SCAN_QUEUE], ["KEEP-ME"])
        self.assertIn(b"Queue (1)", remove.data)

        preview = self.client.get("/return/preview")
        self.assertEqual(preview.status_code, 200)
        self.assertIn(b"KEEP-ME", preview.data)
        self.assertNotIn(b"REMOVE-ME", preview.data)

    def test_return_case_scan_expands_assets_by_home_case(self) -> None:
        self._insert_slot(70, "CASE-2", 1, None)
        self._insert_slot(71, "CASE-2", 2, None)
        self._insert_slot(72, "CASE-2", 3, None)
        self._insert_asset("RT-100", location_type="IN_CUSTODY", holder_id=5, home_slot_id=70)
        self._insert_asset("RT-101", location_type="IN_CUSTODY", holder_id=6, home_slot_id=71)

        response = self.client.post(
            "/",
            data={"scan_text": "case-2", "return_to": "/return"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([scan.asset_tag for scan in intake_app.SCAN_QUEUE], ["RT100", "RT101"])
        self.assertIn(b"Case CASE-2 added 2 assets to queue.", response.data)
        self.assertIn(b"Queue (2)", response.data)
        self.assertNotIn(b"CASE2", response.data)

    def test_return_case_scan_excludes_assets_already_returned_to_storage(self) -> None:
        self._insert_slot(73, "CASE-3", 1, current_asset_tag="RT-300")
        self._insert_slot(74, "CASE-3", 2, None)
        self._insert_asset("RT-300", location_type="STORAGE", holder_id=None, home_slot_id=73)
        self._insert_asset("RT-301", location_type="IN_CUSTODY", holder_id=6, home_slot_id=74)

        response = self.client.post(
            "/",
            data={"scan_text": "CASE-3", "return_to": "/return"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([scan.asset_tag for scan in intake_app.SCAN_QUEUE], ["RT301"])
        self.assertIn(b"Case CASE-3 added 1 asset to queue.", response.data)
        self.assertNotIn(b"RT300", response.data)

    def test_return_case_scan_skips_assets_already_queued(self) -> None:
        self._insert_slot(80, "CASE-20", 1, None)
        self._insert_slot(81, "CASE-20", 2, None)
        self._insert_asset("RT-200", location_type="IN_CUSTODY", holder_id=5, home_slot_id=80)
        self._insert_asset("RT-201", location_type="IN_CUSTODY", holder_id=6, home_slot_id=81)

        intake_app.SCAN_QUEUE.append(intake_app.Scan.now("RT200"))

        response = self.client.post(
            "/",
            data={"scan_text": "CASE20", "return_to": "/return"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([scan.asset_tag for scan in intake_app.SCAN_QUEUE], ["RT200", "RT201"])
        self.assertIn(b"Case CASE-20 added 1 asset to queue. Skipped 1 already queued.", response.data)

    def test_return_case_scan_allows_selective_removal_before_preview(self) -> None:
        self._insert_slot(90, "CASE-30", 1, None)
        self._insert_slot(91, "CASE-30", 2, None)
        self._insert_asset("RT-300", location_type="IN_CUSTODY", holder_id=5, home_slot_id=90)
        self._insert_asset("RT-301", location_type="IN_CUSTODY", holder_id=6, home_slot_id=91)

        scanned = self.client.post(
            "/",
            data={"scan_text": "CASE-30", "return_to": "/return"},
            follow_redirects=True,
        )
        self.assertEqual(scanned.status_code, 200)
        self.assertEqual([scan.asset_tag for scan in intake_app.SCAN_QUEUE], ["RT300", "RT301"])

        removed = self.client.post(
            "/",
            data={"action": "remove", "queue_index": "0", "return_to": "/return"},
            follow_redirects=True,
        )

        self.assertEqual(removed.status_code, 200)
        self.assertEqual([scan.asset_tag for scan in intake_app.SCAN_QUEUE], ["RT301"])
        self.assertIn(b"Queue (1)", removed.data)

        preview = self.client.get("/return/preview")
        self.assertEqual(preview.status_code, 200)
        self.assertIn(b"RT-301", preview.data)
        self.assertNotIn(b"RT-300", preview.data)

    def test_return_scan_normalizes_asset_tag_to_uppercase_and_blocks_case_variant_duplicate(self) -> None:
        self._insert_slot(26, "CASE-RT", 2, None)
        self._insert_asset("RT200", location_type="IN_CUSTODY", holder_id=9, home_slot_id=26)

        first = self.client.post(
            "/",
            data={"scan_text": "rt-200", "return_to": "/return"},
            follow_redirects=True,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual([scan.asset_tag for scan in intake_app.SCAN_QUEUE], ["RT200"])
        self.assertIn(b"RT200", first.data)
        self.assertNotIn(b"rt-200", first.data)

        second = self.client.post(
            "/",
            data={"scan_text": "RT200", "return_to": "/return"},
            follow_redirects=True,
        )

        self.assertEqual(second.status_code, 200)
        self.assertEqual([scan.asset_tag for scan in intake_app.SCAN_QUEUE], ["RT200"])
        self.assertIn(b"Asset RT200 is already queued.", second.data)

        preview = self.client.get("/return/preview")
        self.assertEqual(preview.status_code, 200)
        self.assertIn(b"RT200", preview.data)
        self.assertNotIn(b"rt-200", preview.data)

    def test_return_scan_redirects_back_to_queue_anchor(self) -> None:
        self._insert_slot(25, "CASE-Z", 1, None)
        self._insert_asset("RT-ANCHOR-1", location_type="IN_CUSTODY", holder_id=5, home_slot_id=25)

        response = self.client.post(
            "/",
            data={"scan_text": "rt-anchor-1", "return_to": "/return"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers.get("Location") or "").endswith("/return#queue-section"))

    def test_return_scan_validation_error_redirects_back_to_queue_anchor(self) -> None:
        response = self.client.post(
            "/",
            data={"scan_text": "missing-tag", "return_to": "/return"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers.get("Location") or "").endswith("/return#queue-section"))


if __name__ == "__main__":
    unittest.main()
