from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import assettrack.db as db
from assettrack.intake import app as intake_app


class HolderCreationViabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "assettrack.db"
        self.conn = db.get_connection()
        intake_app.app.testing = True
        self.client = intake_app.app.test_client()
        with self.client.session_transaction() as session:
            session["authed"] = True

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_get_holders_new_route_exists(self) -> None:
        response = self.client.get("/holders/new")
        self.assertEqual(response.status_code, 200)

    def test_post_holders_new_persists_holder(self) -> None:
        holder_name = "Viability Gate Holder"
        self.client.post(
            "/holders/new",
            data={"name": holder_name},
        )

        row = self.conn.execute(
            "SELECT id, name FROM holders WHERE name = ?;",
            (holder_name,),
        ).fetchone()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
