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

    def _create_org(self, name: str) -> int:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO organizations (name, created_at, updated_at)
            VALUES (?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """,
            (name,),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM organizations WHERE name = ?;",
            (name,),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def test_get_holders_new_route_exists(self) -> None:
        response = self.client.get("/holders/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Create Holder", response.data)
        self.assertIn(b"required for receipts", response.data)
        self.assertIn(b'class="form-input"', response.data)
        self.assertIn(b'class="form-select"', response.data)
        self.assertIn(b"novalidate", response.data)
        self.assertNotIn(b'name="organization_id" required', response.data)

    def test_get_holders_list_route_exists(self) -> None:
        response = self.client.get("/holders/list")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/holders"))

    def test_post_holders_new_persists_holder(self) -> None:
        holder_name = "Viability Gate Holder"
        org_id = self._create_org("Alpha Org")
        response = self.client.post(
            "/holders/new",
            data={"name": holder_name, "organization_id": str(org_id), "email": "holder@example.org"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/holders"))

        row = self.conn.execute(
            "SELECT id, name, organization, organization_id, email FROM holders WHERE name = ?;",
            (holder_name,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["organization"], "Alpha Org")
        self.assertEqual(int(row["organization_id"]), org_id)
        self.assertEqual(row["email"], "holder@example.org")

    def test_post_holders_new_rejects_missing_organization(self) -> None:
        response = self.client.post(
            "/holders/new",
            data={"name": "Named Holder", "organization_id": "", "email": "named@example.org"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers["Location"]).endswith("/holders/new"))

        follow_up = self.client.get("/holders/new")
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn(b"Choose an organization for this holder.", follow_up.data)
        self.assertIn(b'value="Named Holder"', follow_up.data)

        count = self.conn.execute("SELECT COUNT(*) AS c FROM holders;").fetchone()["c"]
        self.assertEqual(count, 0)

    def test_post_holders_new_allows_group_only_holder(self) -> None:
        organization_id = self._create_org("Maintenance Shop")
        response = self.client.post(
            "/holders/new",
            data={"name": "", "organization_id": str(organization_id), "email": "shop@example.org"},
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

    def test_post_holders_new_rejects_blank_name_for_ad_hoc(self) -> None:
        organization_id = self._create_org("Ad Hoc")

        response = self.client.post(
            "/holders/new",
            data={"name": "", "organization_id": str(organization_id), "email": "adhoc@example.org"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers["Location"]).endswith("/holders/new"))

        follow_up = self.client.get("/holders/new")
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn(b"Enter a person or group name when using Ad Hoc.", follow_up.data)

    def test_create_search_and_select_holder_workflow(self) -> None:
        holder_name = "ZZ Test Holder 21-4"
        organization_id = self._create_org("Bravo Org")

        create_response = self.client.post(
            "/holders/new",
            data={"name": holder_name, "organization_id": str(organization_id), "email": "zz-holder@example.org"},
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
        org_one_id = self._create_org("Org One")
        org_two_id = self._create_org("Org Two")

        self.client.post(
            "/holders/new",
            data={"name": "Editable Holder", "organization_id": str(org_one_id), "email": "editable@example.org"},
        )
        holder_row = self.conn.execute(
            "SELECT id FROM holders WHERE name = ?;",
            ("Editable Holder",),
        ).fetchone()
        self.assertIsNotNone(holder_row)

        edit_get = self.client.get(f"/holders/edit/{int(holder_row['id'])}")
        self.assertEqual(edit_get.status_code, 200)
        self.assertIn(b"Edit Holder", edit_get.data)
        self.assertIn(b'class="form-input"', edit_get.data)
        self.assertIn(b'class="form-select"', edit_get.data)
        self.assertIn(b"novalidate", edit_get.data)
        self.assertNotIn(b'name="organization_id" required', edit_get.data)

        edit_post = self.client.post(
            f"/holders/edit/{int(holder_row['id'])}",
            data={"name": "Editable Holder", "organization_id": str(org_two_id), "email": "updated@example.org"},
            follow_redirects=True,
        )
        self.assertEqual(edit_post.status_code, 200)
        self.assertIn(b"Updated holder: Editable Holder", edit_post.data)

        updated = self.conn.execute(
            "SELECT organization, organization_id, email FROM holders WHERE id = ?;",
            (int(holder_row["id"]),),
        ).fetchone()
        self.assertEqual(updated["organization"], "Org Two")
        self.assertEqual(int(updated["organization_id"]), org_two_id)
        self.assertEqual(updated["email"], "updated@example.org")

    def test_edit_holder_rejects_missing_organization(self) -> None:
        org_id = self._create_org("Org One")
        self.client.post(
            "/holders/new",
            data={"name": "Editable Holder", "organization_id": str(org_id), "email": "editable@example.org"},
        )
        holder_row = self.conn.execute(
            "SELECT id FROM holders WHERE name = ?;",
            ("Editable Holder",),
        ).fetchone()
        self.assertIsNotNone(holder_row)

        edit_post = self.client.post(
            f"/holders/edit/{int(holder_row['id'])}",
            data={"name": "Editable Holder", "organization_id": "", "email": "editable@example.org"},
            follow_redirects=False,
        )

        self.assertEqual(edit_post.status_code, 302)
        self.assertTrue((edit_post.headers["Location"]).endswith(f"/holders/edit/{int(holder_row['id'])}"))

        follow_up = self.client.get(f"/holders/edit/{int(holder_row['id'])}")
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn(b"Choose an organization for this holder.", follow_up.data)
        self.assertIn(b'value="Editable Holder"', follow_up.data)

    def test_create_holder_respects_return_to_after_success(self) -> None:
        organization_id = self._create_org("Issue Org")

        response = self.client.post(
            "/holders/new",
            data={
                "name": "Workflow Holder",
                "organization_id": str(organization_id),
                "email": "workflow@example.org",
                "return_to": "/issue",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers["Location"]).endswith("/issue"))

    def test_create_holder_preserves_return_to_on_validation_redirect(self) -> None:
        response = self.client.post(
            "/holders/new",
            data={
                "name": "Workflow Holder",
                "organization_id": "",
                "email": "workflow@example.org",
                "return_to": "/issue",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers["Location"]).endswith("/holders/new?return_to=/issue"))

        follow_up = self.client.get("/holders/new?return_to=/issue")
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn(b'name="return_to" value="/issue"', follow_up.data)
        self.assertIn(b"Choose an organization for this holder.", follow_up.data)

    def test_edit_holder_respects_return_to_after_success(self) -> None:
        organization_id = self._create_org("Issue Org")
        self.client.post(
            "/holders/new",
            data={"name": "Workflow Holder", "organization_id": str(organization_id), "email": "workflow@example.org"},
        )
        holder_row = self.conn.execute(
            "SELECT id FROM holders WHERE name = ?;",
            ("Workflow Holder",),
        ).fetchone()
        self.assertIsNotNone(holder_row)

        response = self.client.post(
            f"/holders/edit/{int(holder_row['id'])}",
            data={
                "name": "Workflow Holder",
                "organization_id": str(organization_id),
                "email": "workflow@example.org",
                "return_to": "/issue",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers["Location"]).endswith("/issue"))

    def test_holders_list_shows_holders_and_asset_count(self) -> None:
        holder_name = "Holder List Person"
        organization_id = self._create_org("Ad Hoc")
        self.client.post(
            "/holders/new",
            data={"name": holder_name, "organization_id": str(organization_id), "email": "holder-search@example.org"},
        )
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
        organization_id = self._create_org("Ad Hoc")
        self.client.post(
            "/holders/new",
            data={"name": "Alpha Holder", "organization_id": str(organization_id), "email": "alpha@example.org"},
        )
        self.client.post(
            "/holders/new",
            data={"name": "Bravo Holder", "organization_id": str(organization_id), "email": "bravo@example.org"},
        )

        response = self.client.get("/holders")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Holder Directory", response.data)
        self.assertIn(b"Alpha Holder", response.data)
        self.assertIn(b"Bravo Holder", response.data)
        self.assertIn(b"Search by person name, group, organization, or identifier", response.data)

    def test_holder_detail_shows_metadata_and_assigned_assets(self) -> None:
        organization_id = self._create_org("Org Detail")
        self.client.post(
            "/holders/new",
            data={"name": "Detail Holder", "organization_id": str(organization_id), "email": "detail@example.org"},
        )
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
        self.assertIn(b"Email:</strong>", response.data)
        self.assertIn(b"Assigned Assets (1)", response.data)
        self.assertIn(b"DETAIL-ASSET-1", response.data)
        self.assertIn(f'href="/holders/edit/{holder_id}"'.encode("utf-8"), response.data)

    def test_post_holders_new_rejects_invalid_email_with_clear_feedback(self) -> None:
        org_id = self._create_org("Alpha Org")

        response = self.client.post(
            "/holders/new",
            data={"name": "Invalid Email Holder", "organization_id": str(org_id), "email": "bad-email"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers["Location"]).endswith("/holders/new"))

        follow_up = self.client.get("/holders/new")
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn(b"Enter a valid email address so this holder can receive receipts.", follow_up.data)
        self.assertIn(b'value="bad-email"', follow_up.data)

    def test_post_holders_new_rejects_missing_email_with_clear_feedback(self) -> None:
        org_id = self._create_org("Alpha Org")

        response = self.client.post(
            "/holders/new",
            data={"name": "Missing Email Holder", "organization_id": str(org_id), "email": ""},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers["Location"]).endswith("/holders/new"))

        follow_up = self.client.get("/holders/new")
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn(b"Enter an email address so this holder can receive receipts.", follow_up.data)
        self.assertIn(b'value="Missing Email Holder"', follow_up.data)

    def test_post_holders_new_rejects_duplicate_email_with_clear_feedback(self) -> None:
        org_id = self._create_org("Alpha Org")
        self.client.post(
            "/holders/new",
            data={"name": "First Holder", "organization_id": str(org_id), "email": "shared@example.org"},
        )

        response = self.client.post(
            "/holders/new",
            data={"name": "Second Holder", "organization_id": str(org_id), "email": "shared@example.org"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers["Location"]).endswith("/holders/new"))

        follow_up = self.client.get("/holders/new")
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn(b"A holder with that email already exists.", follow_up.data)
        self.assertIn(b'value="Second Holder"', follow_up.data)
        self.assertIn(b'value="shared@example.org"', follow_up.data)

    def test_edit_holder_rejects_invalid_email_with_clear_feedback(self) -> None:
        org_id = self._create_org("Alpha Org")
        self.client.post(
            "/holders/new",
            data={"name": "Editable Holder", "organization_id": str(org_id), "email": "editable@example.org"},
        )
        holder_row = self.conn.execute(
            "SELECT id FROM holders WHERE name = ?;",
            ("Editable Holder",),
        ).fetchone()
        self.assertIsNotNone(holder_row)

        response = self.client.post(
            f"/holders/edit/{int(holder_row['id'])}",
            data={"name": "Editable Holder", "organization_id": str(org_id), "email": "bad-email"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers["Location"]).endswith(f"/holders/edit/{int(holder_row['id'])}"))

        follow_up = self.client.get(f"/holders/edit/{int(holder_row['id'])}")
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn(b"Enter a valid email address so this holder can receive receipts.", follow_up.data)
        self.assertIn(b'value="bad-email"', follow_up.data)

    def test_edit_holder_rejects_missing_email_with_clear_feedback(self) -> None:
        org_id = self._create_org("Alpha Org")
        self.client.post(
            "/holders/new",
            data={"name": "Editable Holder", "organization_id": str(org_id), "email": "editable@example.org"},
        )
        holder_row = self.conn.execute(
            "SELECT id FROM holders WHERE name = ?;",
            ("Editable Holder",),
        ).fetchone()
        self.assertIsNotNone(holder_row)

        response = self.client.post(
            f"/holders/edit/{int(holder_row['id'])}",
            data={"name": "Editable Holder", "organization_id": str(org_id), "email": ""},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers["Location"]).endswith(f"/holders/edit/{int(holder_row['id'])}"))

        follow_up = self.client.get(f"/holders/edit/{int(holder_row['id'])}")
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn(b"Enter an email address so this holder can receive receipts.", follow_up.data)
        self.assertIn(b'value="Editable Holder"', follow_up.data)

    def test_edit_holder_rejects_duplicate_email_with_clear_feedback(self) -> None:
        org_id = self._create_org("Alpha Org")
        self.client.post(
            "/holders/new",
            data={"name": "First Holder", "organization_id": str(org_id), "email": "first@example.org"},
        )
        self.client.post(
            "/holders/new",
            data={"name": "Second Holder", "organization_id": str(org_id), "email": "second@example.org"},
        )
        holder_row = self.conn.execute(
            "SELECT id FROM holders WHERE name = ?;",
            ("Second Holder",),
        ).fetchone()
        self.assertIsNotNone(holder_row)

        response = self.client.post(
            f"/holders/edit/{int(holder_row['id'])}",
            data={"name": "Second Holder", "organization_id": str(org_id), "email": "first@example.org"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue((response.headers["Location"]).endswith(f"/holders/edit/{int(holder_row['id'])}"))

        follow_up = self.client.get(f"/holders/edit/{int(holder_row['id'])}")
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn(b"A holder with that email already exists.", follow_up.data)
        self.assertIn(b'value="Second Holder"', follow_up.data)
        self.assertIn(b'value="first@example.org"', follow_up.data)

    def test_edit_holder_allows_unchanged_same_holder_email(self) -> None:
        org_id = self._create_org("Alpha Org")
        self.client.post(
            "/holders/new",
            data={"name": "Editable Holder", "organization_id": str(org_id), "email": "editable@example.org"},
            follow_redirects=False,
        )
        holder_row = self.conn.execute(
            "SELECT id FROM holders WHERE name = ?;",
            ("Editable Holder",),
        ).fetchone()
        self.assertIsNotNone(holder_row)

        response = self.client.post(
            f"/holders/edit/{int(holder_row['id'])}",
            data={"name": "Editable Holder Renamed", "organization_id": str(org_id), "email": "editable@example.org"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Updated holder: Editable Holder Renamed", response.data)

    def test_holder_detail_shows_zero_assets_state(self) -> None:
        organization_id = self._create_org("Ad Hoc")
        self.client.post(
            "/holders/new",
            data={"name": "Empty Holder", "organization_id": str(organization_id), "email": "empty@example.org"},
        )
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
        organization_id = self._create_org("Ops Section")
        self.client.post(
            "/holders/new",
            data={"name": "", "organization_id": str(organization_id), "email": "ops-section@example.org"},
        )
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
