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

    def test_post_holders_new_persists_holder(self) -> None:
        holder_name = "Viability Gate Holder"
        response = self.client.post(
            "/holders/new",
            data={"name": holder_name},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/holders"))

        row = self.conn.execute(
            "SELECT id, name FROM holders WHERE name = ?;",
            (holder_name,),
        ).fetchone()
        self.assertIsNotNone(row)

    def test_post_holders_new_rejects_blank_name(self) -> None:
        response = self.client.post(
            "/holders/new",
            data={"name": "   "},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Name is required.", response.data)

        count = self.conn.execute("SELECT COUNT(*) AS c FROM holders;").fetchone()["c"]
        self.assertEqual(count, 0)

    def test_create_search_and_select_holder_workflow(self) -> None:
        holder_name = "ZZ Test Holder 21-4"

        create_response = self.client.post(
            "/holders/new",
            data={"name": holder_name},
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


if __name__ == "__main__":
    unittest.main()
