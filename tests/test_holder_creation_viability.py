from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


class HolderCreationViabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "assettrack.db"
        self.conn = db.get_connection()
        intake_app.app.testing = True
        self.client = intake_app.app.test_client()
        user_id = create_test_user(username="operator", password="op-pass", role="operator")
        login_session(self.client, user_id)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_get_holders_new_route_exists(self) -> None:
        response = self.client.get("/holders/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Create Holder", response.data)

    def test_get_holders_list_route_exists(self) -> None:
        response = self.client.get("/holders/list")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/holders"))

    def test_post_holders_new_persists_holder(self) -> None:
        holder_name = "Viability Gate Holder"
        org = self.conn.execute(
            """
            INSERT INTO organizations (name, created_at, updated_at)
            VALUES ('Alpha Org', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        self.conn.commit()
        response = self.client.post(
            "/holders/new",
            data={"name": holder_name, "organization_id": str(org.lastrowid)},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/holders"))

        row = self.conn.execute(
            "SELECT id, name, organization, organization_id FROM holders WHERE name = ?;",
            (holder_name,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["organization"], "Alpha Org")
        self.assertEqual(int(row["organization_id"]), int(org.lastrowid))

    def test_post_holders_new_rejects_blank_name(self) -> None:
        response = self.client.post(
            "/holders/new",
            data={"name": "   ", "organization": "   "},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Enter a person or group name, or enter a group / organization.", response.data)

        count = self.conn.execute("SELECT COUNT(*) AS c FROM holders;").fetchone()["c"]
        self.assertEqual(count, 0)

    def test_post_holders_new_allows_group_only_holder(self) -> None:
        response = self.client.post(
            "/holders/new",
            data={"name": "", "organization": "Maintenance Shop"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Created holder: Maintenance Shop", response.data)
        self.assertIn(b"Maintenance Shop", response.data)

        row = self.conn.execute(
            "SELECT holder_type, name, organization FROM holders WHERE name = ?;",
            ("Maintenance Shop",),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["holder_type"], "ORGANIZATION")
        self.assertEqual(row["organization"], "Maintenance Shop")

    def test_create_search_and_select_holder_workflow(self) -> None:
        holder_name = "ZZ Test Holder 21-4"

        create_response = self.client.post(
            "/holders/new",
            data={"name": holder_name, "organization": "Bravo Org"},
        )
        self.assertEqual(create_response.status_code, 302)
        self.assertTrue(create_response.headers["Location"].endswith("/holders"))

        holder_row = self.conn.execute(
            "SELECT id, name FROM holders WHERE name = ?;",
            (holder_name,),
        ).fetchone()
        self.assertIsNotNone(holder_row)
        holder_id = int(holder_row["id"])

        search_response = self.client.get(
            "/holders",
            query_string={"q": holder_name},
        )
        self.assertEqual(search_response.status_code, 200)
        self.assertIn(holder_name.encode("utf-8"), search_response.data)

        select_response = self.client.post(
            "/holders/select",
            data={"holder_id": str(holder_id)},
            follow_redirects=True,
        )
        self.assertEqual(select_response.status_code, 200)
        self.assertIn(f"Selected holder: {holder_name}".encode("utf-8"), select_response.data)
        self.assertIn(b"Bravo Org", select_response.data)

    def test_edit_holder_updates_organization(self) -> None:
        org_one = self.conn.execute(
            """
            INSERT INTO organizations (name, created_at, updated_at)
            VALUES ('Org One', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        org_two = self.conn.execute(
            """
            INSERT INTO organizations (name, created_at, updated_at)
            VALUES ('Org Two', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        self.conn.commit()

        self.client.post("/holders/new", data={"name": "Editable Holder", "organization_id": str(org_one.lastrowid)})
        holder_row = self.conn.execute(
            "SELECT id FROM holders WHERE name = ?;",
            ("Editable Holder",),
        ).fetchone()
        self.assertIsNotNone(holder_row)

        edit_get = self.client.get(f"/holders/edit/{int(holder_row['id'])}")
        self.assertEqual(edit_get.status_code, 200)
        self.assertIn(b"Edit Holder", edit_get.data)

        edit_post = self.client.post(
            f"/holders/edit/{int(holder_row['id'])}",
            data={"name": "Editable Holder", "organization_id": str(org_two.lastrowid)},
            follow_redirects=True,
        )
        self.assertEqual(edit_post.status_code, 200)
        self.assertIn(b"Updated holder: Editable Holder", edit_post.data)

        updated = self.conn.execute(
            "SELECT organization, organization_id FROM holders WHERE id = ?;",
            (int(holder_row["id"]),),
        ).fetchone()
        self.assertEqual(updated["organization"], "Org Two")
        self.assertEqual(int(updated["organization_id"]), int(org_two.lastrowid))

    def test_holders_list_shows_holders_and_asset_count(self) -> None:
        holder_name = "Holder List Person"
        self.client.post("/holders/new", data={"name": holder_name})
        holder_row = self.conn.execute(
            "SELECT id FROM holders WHERE name = ?;",
            (holder_name,),
        ).fetchone()
        self.assertIsNotNone(holder_row)
        holder_id = int(holder_row["id"])

        self.conn.execute(
            "INSERT INTO assets (asset_tag, current_holder_id) VALUES (?, ?);",
            ("HOLDER-LIST-ASSET-1", holder_id),
        )
        self.conn.commit()

        response = self.client.get("/holders")
        self.assertEqual(response.status_code, 200)
        self.assertIn(holder_name.encode("utf-8"), response.data)
        self.assertIn(b">1<", response.data)
        self.assertIn(f'href="/holders/{holder_id}"'.encode("utf-8"), response.data)

    def test_holders_directory_loads_by_default_without_search(self) -> None:
        self.client.post("/holders/new", data={"name": "Alpha Holder"})
        self.client.post("/holders/new", data={"name": "Bravo Holder"})

        response = self.client.get("/holders")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Holder Directory", response.data)
        self.assertIn(b"Alpha Holder", response.data)
        self.assertIn(b"Bravo Holder", response.data)
        self.assertIn(b"Search by person name, group, organization, or identifier", response.data)

    def test_holder_detail_shows_metadata_and_assigned_assets(self) -> None:
        self.client.post("/holders/new", data={"name": "Detail Holder", "organization": "Org Detail"})
        holder_row = self.conn.execute(
            "SELECT id FROM holders WHERE name = ?;",
            ("Detail Holder",),
        ).fetchone()
        self.assertIsNotNone(holder_row)
        holder_id = int(holder_row["id"])

        self.conn.execute(
            """
            INSERT INTO assets (asset_tag, equipment_type, manufacturer, model, location_type, current_holder_id)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            ("DETAIL-ASSET-1", "LAPTOP", "Dell", "Latitude", "IN_CUSTODY", holder_id),
        )
        self.conn.commit()

        response = self.client.get(f"/holders/{holder_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Holder: Detail Holder", response.data)
        self.assertIn(b"Organization:</strong> Org Detail", response.data)
        self.assertIn(b"Assigned Assets (1)", response.data)
        self.assertIn(b"DETAIL-ASSET-1", response.data)
        self.assertIn(f'href="/holders/edit/{holder_id}"'.encode("utf-8"), response.data)

    def test_holder_detail_shows_zero_assets_state(self) -> None:
        self.client.post("/holders/new", data={"name": "Empty Holder", "organization": "None"})
        holder_row = self.conn.execute(
            "SELECT id FROM holders WHERE name = ?;",
            ("Empty Holder",),
        ).fetchone()
        self.assertIsNotNone(holder_row)

        response = self.client.get(f"/holders/{int(holder_row['id'])}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Assigned Assets (0)", response.data)
        self.assertIn(b"No assigned assets.", response.data)

    def test_holder_detail_displays_group_holder_cleanly(self) -> None:
        self.client.post("/holders/new", data={"name": "", "organization": "Ops Section"})
        holder_row = self.conn.execute(
            "SELECT id FROM holders WHERE name = ?;",
            ("Ops Section",),
        ).fetchone()
        self.assertIsNotNone(holder_row)

        response = self.client.get(f"/holders/{int(holder_row['id'])}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Type:</strong> Group / organization", response.data)
        self.assertIn(b"Person or group:</strong> Ops Section", response.data)


if __name__ == "__main__":
    unittest.main()
