from __future__ import annotations

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
