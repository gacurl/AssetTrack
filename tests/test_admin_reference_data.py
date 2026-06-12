from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


class AdminReferenceDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "assettrack.db"
        self.conn = db.get_connection()
        intake_app.app.testing = True
        self.client = intake_app.app.test_client()

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_operator_cannot_access_admin_reference_data(self) -> None:
        operator_id = create_test_user(username="operator-ref", password="op-pass", role="operator")
        login_session(self.client, operator_id)

        response = self.client.get("/admin/reference-data")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_organization_building_and_mapping(self) -> None:
        admin_id = create_test_user(username="admin-ref", password="admin-pass", role="admin")
        login_session(self.client, admin_id)

        response = self.client.get("/admin/reference-data")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Organizations", response.data)
        self.assertIn(b"Buildings", response.data)
        self.assertIn(b"box-sizing: border-box;", response.data)

        create_org = self.client.post(
            "/admin/reference-data",
            data={"action": "create_organization", "organization_name": "Operations"},
            follow_redirects=True,
        )
        self.assertEqual(create_org.status_code, 200)
        self.assertIn(b"Created organization.", create_org.data)

        create_building = self.client.post(
            "/admin/reference-data",
            data={"action": "create_building", "building_name": "HQ North"},
            follow_redirects=True,
        )
        self.assertEqual(create_building.status_code, 200)
        self.assertIn(b"Created building.", create_building.data)

        org_row = self.conn.execute(
            "SELECT id, name FROM organizations WHERE name = ?;",
            ("Operations",),
        ).fetchone()
        self.assertIsNotNone(org_row)

        building_row = self.conn.execute(
            "SELECT id, name FROM buildings WHERE name = ?;",
            ("HQ North",),
        ).fetchone()
        self.assertIsNotNone(building_row)

        create_map = self.client.post(
            "/admin/reference-data",
            data={
                "action": "map_organization_building",
                "organization_id": str(org_row["id"]),
                "building_id": str(building_row["id"]),
            },
            follow_redirects=True,
        )
        self.assertEqual(create_map.status_code, 200)
        self.assertIn(b"Created organization to building mapping.", create_map.data)
        self.assertIn(b"Operations", create_map.data)
        self.assertIn(b"HQ North", create_map.data)

        mapping = self.conn.execute(
            """
            SELECT organization_id, building_id
            FROM organization_buildings
            WHERE organization_id = ? AND building_id = ?;
            """,
            (org_row["id"], building_row["id"]),
        ).fetchone()
        self.assertIsNotNone(mapping)

    def test_admin_can_correct_building_name_for_reference_displays(self) -> None:
        admin_id = create_test_user(username="admin-ref-correct", password="admin-pass", role="admin")
        login_session(self.client, admin_id)

        self.conn.execute(
            """
            INSERT INTO organizations (name, created_at, updated_at)
            VALUES ('Operations', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        org_row = self.conn.execute(
            "SELECT id FROM organizations WHERE name = 'Operations';"
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO buildings (name, created_at, updated_at)
            VALUES ('HQ Nroth', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        building_row = self.conn.execute(
            "SELECT id FROM buildings WHERE name = 'HQ Nroth';"
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO organization_buildings (organization_id, building_id, created_at)
            VALUES (?, ?, '2026-01-01T00:00:00Z');
            """,
            (org_row["id"], building_row["id"]),
        )
        self.conn.execute(
            """
            INSERT INTO holders (
                holder_type, name, organization, organization_id, identifier, contact_info, created_at, updated_at
            )
            VALUES ('PERSON', 'Issue Holder', 'Operations', ?, 'IH-1', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """,
            (org_row["id"],),
        )
        self.conn.commit()

        response = self.client.post(
            "/admin/reference-data",
            data={
                "action": "update_building_name",
                "building_id": str(building_row["id"]),
                "building_name": "HQ North",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Updated building name.", response.data)
        self.assertIn(b"HQ North", response.data)
        self.assertNotIn(b"HQ Nroth", response.data)

        updated_row = self.conn.execute(
            "SELECT name FROM buildings WHERE id = ?;",
            (building_row["id"],),
        ).fetchone()
        self.assertEqual(updated_row["name"], "HQ North")

        operator_id = create_test_user(username="operator-ref-correct", password="op-pass", role="operator")
        login_session(self.client, operator_id)
        with self.client.session_transaction() as sess:
            sess["holder_id"] = 1
            sess["issue_mode"] = True

        issue_page = self.client.get("/issue")

        self.assertEqual(issue_page.status_code, 200)
        self.assertIn(b"HQ North", issue_page.data)
        self.assertNotIn(b"HQ Nroth", issue_page.data)

    def test_operator_cannot_correct_building_name(self) -> None:
        self.conn.execute(
            """
            INSERT INTO buildings (name, created_at, updated_at)
            VALUES ('HQ Nroth', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        self.conn.commit()
        building_row = self.conn.execute(
            "SELECT id FROM buildings WHERE name = 'HQ Nroth';"
        ).fetchone()

        operator_id = create_test_user(username="operator-ref-correct-denied", password="op-pass", role="operator")
        login_session(self.client, operator_id)

        response = self.client.post(
            "/admin/reference-data",
            data={
                "action": "update_building_name",
                "building_id": str(building_row["id"]),
                "building_name": "HQ North",
            },
        )

        self.assertEqual(response.status_code, 403)
        unchanged = self.conn.execute(
            "SELECT name FROM buildings WHERE id = ?;",
            (building_row["id"],),
        ).fetchone()
        self.assertEqual(unchanged["name"], "HQ Nroth")

    def test_building_name_correction_validates_blank_and_duplicate_names(self) -> None:
        admin_id = create_test_user(username="admin-ref-correct-validation", password="admin-pass", role="admin")
        login_session(self.client, admin_id)
        self.conn.execute(
            """
            INSERT INTO buildings (name, created_at, updated_at)
            VALUES
                ('HQ North', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
                ('Warehouse West', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        self.conn.commit()
        warehouse_row = self.conn.execute(
            "SELECT id FROM buildings WHERE name = 'Warehouse West';"
        ).fetchone()

        blank_response = self.client.post(
            "/admin/reference-data",
            data={
                "action": "update_building_name",
                "building_id": str(warehouse_row["id"]),
                "building_name": "   ",
            },
            follow_redirects=True,
        )
        self.assertEqual(blank_response.status_code, 200)
        self.assertIn(b"name is required", blank_response.data)

        duplicate_response = self.client.post(
            "/admin/reference-data",
            data={
                "action": "update_building_name",
                "building_id": str(warehouse_row["id"]),
                "building_name": "hq north",
            },
            follow_redirects=True,
        )
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertIn(b"building already exists", duplicate_response.data)

        unchanged = self.conn.execute(
            "SELECT name FROM buildings WHERE id = ?;",
            (warehouse_row["id"],),
        ).fetchone()
        self.assertEqual(unchanged["name"], "Warehouse West")

    def test_building_name_correction_does_not_rewrite_events_or_receipt_snapshots(self) -> None:
        admin_id = create_test_user(username="admin-ref-correct-history", password="admin-pass", role="admin")
        login_session(self.client, admin_id)
        self.conn.execute(
            """
            INSERT INTO buildings (name, created_at, updated_at)
            VALUES ('HQ Nroth', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        building_row = self.conn.execute(
            "SELECT id FROM buildings WHERE name = 'HQ Nroth';"
        ).fetchone()
        event_payload = {
            "from_building_room": "Storage/A1",
            "to_building_room": "HQ Nroth/210",
        }
        receipt_snapshot = {
            "receipt_type": "ISSUE",
            "location_context": {
                "building": "HQ Nroth",
                "room": "210",
                "building_room": "HQ Nroth/210",
            },
        }
        self.conn.execute(
            """
            INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
            VALUES ('AT-100', 'ISSUE', '2026-01-01T00:00:00Z', 'admin', NULL, ?, NULL);
            """,
            (json.dumps(event_payload, sort_keys=True),),
        )
        self.conn.execute(
            """
            INSERT INTO receipt_queue (
                receipt_key, receipt_type, source_event_ids_json, snapshot_json, commit_at,
                commit_operator_user_id, holder_id, created_at, updated_at
            )
            VALUES (
                'receipt-history-proof', 'ISSUE', '[1]', ?, '2026-01-01T00:00:00Z',
                ?, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            );
            """,
            (json.dumps(receipt_snapshot, sort_keys=True), admin_id),
        )
        self.conn.commit()
        event_before = self.conn.execute(
            "SELECT payload FROM asset_events WHERE asset_tag = 'AT-100';"
        ).fetchone()["payload"]
        receipt_before = self.conn.execute(
            "SELECT snapshot_json FROM receipt_queue WHERE receipt_key = 'receipt-history-proof';"
        ).fetchone()["snapshot_json"]

        response = self.client.post(
            "/admin/reference-data",
            data={
                "action": "update_building_name",
                "building_id": str(building_row["id"]),
                "building_name": "HQ North",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        event_after = self.conn.execute(
            "SELECT payload FROM asset_events WHERE asset_tag = 'AT-100';"
        ).fetchone()["payload"]
        receipt_after = self.conn.execute(
            "SELECT snapshot_json FROM receipt_queue WHERE receipt_key = 'receipt-history-proof';"
        ).fetchone()["snapshot_json"]
        self.assertEqual(event_after, event_before)
        self.assertEqual(receipt_after, receipt_before)
