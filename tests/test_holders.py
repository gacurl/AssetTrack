# file: tests/test_holders.py
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import assettrack.db as db
from assettrack.holders import create_holder, get_holder, list_holders, search_holders, set_holder_active, update_holder


class HoldersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "assettrack.db"
        self.conn = db.get_connection()

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def _insert_holder(
        self,
        holder_type: str,
        name: str,
        organization: str | None = None,
        organization_id: int | None = None,
        identifier: str | None = None,
        contact_info: str | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            """
            INSERT INTO holders (
                holder_type, name, organization, organization_id, is_active, identifier, contact_info, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (holder_type, name, organization, organization_id, 1, identifier, contact_info, now, now),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def _insert_organization(self, name: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO organizations (name, created_at, updated_at)
            VALUES (?, ?, ?);
            """,
            (name, now, now),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM organizations WHERE name = ?;",
            (name,),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def test_holders_insert_and_get(self) -> None:
        organization_id = self._insert_organization("Ad Hoc")
        holder_id = self._insert_holder(
            holder_type="Person",
            name="Jane Doe",
            organization="Ad Hoc",
            organization_id=organization_id,
            identifier="ID-123",
            contact_info="jane@example.org",
        )
        holder = get_holder(holder_id)
        self.assertIsNotNone(holder)
        self.assertEqual(holder["name"], "Jane Doe")
        self.assertEqual(holder["identifier"], "ID-123")
        self.assertEqual(holder["organization"], "Ad Hoc")
        self.assertIsNone(holder["email"])

    def test_search_holders_by_name_and_identifier(self) -> None:
        ad_hoc_id = self._insert_organization("Ad Hoc")
        bravo_org_id = self._insert_organization("Bravo Group")
        self._insert_holder("Person", "Alpha User", "Ad Hoc", ad_hoc_id, "A-001", None)
        self._insert_holder("Organization", "Bravo Org", "Bravo Group", bravo_org_id, "BR-77", "contact@bravo.org")

        by_name = search_holders("Alpha")
        self.assertEqual(len(by_name), 1)
        self.assertEqual(by_name[0]["name"], "Alpha User")

        by_identifier = search_holders("BR-77")
        self.assertEqual(len(by_identifier), 1)
        self.assertEqual(by_identifier[0]["name"], "Bravo Org")

        by_organization = search_holders("Bravo Group")
        self.assertEqual(len(by_organization), 1)
        self.assertEqual(by_organization[0]["name"], "Bravo Org")

    def test_search_holders_active_only_excludes_inactive_rows(self) -> None:
        ad_hoc_id = self._insert_organization("Ad Hoc")
        active_id = self._insert_holder("Person", "Active User", "Ad Hoc", ad_hoc_id, "A-001", None)
        inactive_id = self._insert_holder("Person", "Inactive User", "Ad Hoc", ad_hoc_id, "I-001", None)
        set_holder_active(inactive_id, False)

        rows = search_holders("User", active_only=True)

        self.assertEqual([row["name"] for row in rows], ["Active User"])
        fetched_inactive = get_holder(inactive_id)
        self.assertIsNotNone(fetched_inactive)
        self.assertEqual(int(fetched_inactive["is_active"]), 0)

    def test_list_holders_includes_asset_count(self) -> None:
        ad_hoc_id = self._insert_organization("Ad Hoc")
        alpha_id = self._insert_holder("Person", "Alpha User", "Ad Hoc", ad_hoc_id, "A-001", None)
        self._insert_holder("Organization", "Bravo Org", "Ad Hoc", ad_hoc_id, "BR-77", "contact@bravo.org")

        self.conn.execute(
            "INSERT INTO assets (asset_tag, current_holder_id) VALUES (?, ?);",
            ("A-TAG-1", alpha_id),
        )
        self.conn.execute(
            "INSERT INTO assets (asset_tag, current_holder_id) VALUES (?, ?);",
            ("A-TAG-2", alpha_id),
        )
        self.conn.commit()

        rows = list_holders()
        self.assertEqual([row["name"] for row in rows], ["Alpha User", "Bravo Org"])
        self.assertEqual(int(rows[0]["asset_count"]), 2)
        self.assertEqual(int(rows[1]["asset_count"]), 0)

    def test_list_holders_active_only_excludes_inactive_rows(self) -> None:
        ad_hoc_id = self._insert_organization("Ad Hoc")
        active_id = self._insert_holder("Person", "Alpha User", "Ad Hoc", ad_hoc_id, "A-001", None)
        inactive_id = self._insert_holder("Person", "Bravo User", "Ad Hoc", ad_hoc_id, "B-001", None)
        set_holder_active(inactive_id, False)

        rows = list_holders(active_only=True)

        self.assertEqual([row["name"] for row in rows], ["Alpha User"])
        self.assertEqual(int(rows[0]["id"]), active_id)

    def test_set_holder_active_toggles_flag_without_removing_holder(self) -> None:
        organization_id = self._insert_organization("Support Org")
        created = create_holder("Stable Holder", organization_id=organization_id, email="stable@example.org")

        updated = set_holder_active(int(created["id"]), False)
        fetched = get_holder(int(created["id"]))

        self.assertEqual(int(updated["is_active"]), 0)
        self.assertIsNotNone(fetched)
        self.assertEqual(int(fetched["is_active"]), 0)

    def test_create_and_update_holder_organization(self) -> None:
        alpha_org_id = self._insert_organization("Alpha Org")
        bravo_org_id = self._insert_organization("Bravo Org")
        created = create_holder("Org Holder", organization_id=alpha_org_id, email="first@example.org")
        self.assertEqual(created["organization"], "Alpha Org")
        self.assertEqual(created["email"], "first@example.org")

        updated = update_holder(
            int(created["id"]),
            name="Org Holder",
            organization_id=bravo_org_id,
            email="second@example.org",
        )
        self.assertEqual(updated["organization"], "Bravo Org")
        self.assertEqual(updated["email"], "second@example.org")

        fetched = get_holder(int(created["id"]))
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["organization"], "Bravo Org")
        self.assertEqual(fetched["email"], "second@example.org")

    def test_create_holder_with_organization_id_sets_denormalized_text(self) -> None:
        organization_id = self._insert_organization("Support Org")

        created = create_holder("Mapped Holder", organization_id=organization_id)

        self.assertEqual(created["organization"], "Support Org")
        self.assertEqual(int(created["organization_id"]), organization_id)

    def test_create_holder_allows_org_only_holder(self) -> None:
        organization_id = self._insert_organization("Field Team")
        created = create_holder("", organization_id=organization_id)
        self.assertEqual(created["holder_type"], "ORGANIZATION")
        self.assertEqual(created["name"], "Field Team")
        self.assertEqual(created["organization"], "Field Team")

    def test_create_holder_requires_organization_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "organization is required"):
            create_holder("Missing Org", organization_id=None)  # type: ignore[arg-type]

    def test_create_holder_requires_name_for_ad_hoc(self) -> None:
        ad_hoc_id = self._insert_organization("Ad Hoc")

        with self.assertRaisesRegex(ValueError, "name is required"):
            create_holder("", organization_id=ad_hoc_id)

    def test_create_holder_rejects_invalid_email(self) -> None:
        organization_id = self._insert_organization("Support Org")

        with self.assertRaisesRegex(ValueError, "email is invalid"):
            create_holder("Bad Email", organization_id=organization_id, email="not-an-email")

    def test_update_holder_allows_clearing_email(self) -> None:
        organization_id = self._insert_organization("Support Org")
        created = create_holder("Email Holder", organization_id=organization_id, email="holder@example.org")

        updated = update_holder(int(created["id"]), name="Email Holder", organization_id=organization_id, email="")

        self.assertIsNone(updated["email"])

    def test_create_holder_rejects_duplicate_email(self) -> None:
        organization_id = self._insert_organization("Support Org")
        create_holder("First Holder", organization_id=organization_id, email="holder@example.org")

        with self.assertRaisesRegex(ValueError, "email already exists"):
            create_holder("Second Holder", organization_id=organization_id, email="holder@example.org")

    def test_update_holder_rejects_duplicate_email_on_different_holder(self) -> None:
        organization_id = self._insert_organization("Support Org")
        first = create_holder("First Holder", organization_id=organization_id, email="first@example.org")
        second = create_holder("Second Holder", organization_id=organization_id, email="second@example.org")

        with self.assertRaisesRegex(ValueError, "email already exists"):
            update_holder(
                int(second["id"]),
                name="Second Holder",
                organization_id=organization_id,
                email="first@example.org",
            )

        fetched = get_holder(int(second["id"]))
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["email"], "second@example.org")

    def test_update_holder_allows_unchanged_email_on_same_holder(self) -> None:
        organization_id = self._insert_organization("Support Org")
        created = create_holder("Stable Holder", organization_id=organization_id, email="stable@example.org")

        updated = update_holder(
            int(created["id"]),
            name="Stable Holder",
            organization_id=organization_id,
            email="stable@example.org",
        )

        self.assertEqual(updated["email"], "stable@example.org")
