# file: tests/test_holders.py
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import assettrack.db as db
from assettrack.holders import create_holder, get_holder, list_holders, search_holders, update_holder


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
        identifier: str | None = None,
        contact_info: str | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            """
            INSERT INTO holders (
                holder_type, name, identifier, contact_info, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (holder_type, name, identifier, contact_info, now, now),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def test_holders_insert_and_get(self) -> None:
        holder_id = self._insert_holder(
            holder_type="Person",
            name="Jane Doe",
            identifier="ID-123",
            contact_info="jane@example.org",
        )
        holder = get_holder(holder_id)
        self.assertIsNotNone(holder)
        self.assertEqual(holder["name"], "Jane Doe")
        self.assertEqual(holder["identifier"], "ID-123")
        self.assertIsNone(holder["organization"])

    def test_search_holders_by_name_and_identifier(self) -> None:
        self._insert_holder("Person", "Alpha User", "A-001", None)
        self._insert_holder("Organization", "Bravo Org", "BR-77", "contact@bravo.org")
        self.conn.execute("UPDATE holders SET organization = 'Bravo Group' WHERE name = 'Bravo Org';")
        self.conn.commit()

        by_name = search_holders("Alpha")
        self.assertEqual(len(by_name), 1)
        self.assertEqual(by_name[0]["name"], "Alpha User")

        by_identifier = search_holders("BR-77")
        self.assertEqual(len(by_identifier), 1)
        self.assertEqual(by_identifier[0]["name"], "Bravo Org")

        by_organization = search_holders("Bravo Group")
        self.assertEqual(len(by_organization), 1)
        self.assertEqual(by_organization[0]["name"], "Bravo Org")

    def test_list_holders_includes_asset_count(self) -> None:
        alpha_id = self._insert_holder("Person", "Alpha User", "A-001", None)
        self._insert_holder("Organization", "Bravo Org", "BR-77", "contact@bravo.org")

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

    def test_create_and_update_holder_organization(self) -> None:
        created = create_holder("Org Holder", organization="Alpha Org")
        self.assertEqual(created["organization"], "Alpha Org")

        updated = update_holder(int(created["id"]), name="Org Holder", organization="Bravo Org")
        self.assertEqual(updated["organization"], "Bravo Org")

        fetched = get_holder(int(created["id"]))
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["organization"], "Bravo Org")
