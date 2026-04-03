from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from assettrack import holder_import
from assettrack.db import bootstrap_db


class HolderImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "assettrack.db"
        bootstrap_db(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_csv(self, name: str, content: str) -> Path:
        path = Path(self.temp_dir.name) / name
        path.write_text(content, encoding="utf-8")
        return path

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _insert_organization(self, name: str) -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO organizations (name, created_at, updated_at)
                VALUES (?, ?, ?);
                """,
                (name, now_iso, now_iso),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def _insert_holder(self, *, name: str, organization: str, organization_id: int, email: str) -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO holders (
                    holder_type, name, organization, organization_id, email, identifier, contact_info, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?);
                """,
                ("PERSON", name, organization, organization_id, email, now_iso, now_iso),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def test_import_creates_new_holder_for_new_email(self) -> None:
        csv_path = self._write_csv(
            "holders.csv",
            "organization,name,email\nOps Alpha,Jane Doe,jane@example.org\n",
        )

        report = holder_import.import_holders_csv(csv_path, db_path=self.db_path)

        self.assertEqual(report.summary(), {"processed": 1, "created": 1, "updated": 0, "errors": 0})
        conn = self._connection()
        try:
            holder = conn.execute(
                "SELECT name, organization, email FROM holders WHERE email = ?;",
                ("jane@example.org",),
            ).fetchone()
            self.assertIsNotNone(holder)
            self.assertEqual(dict(holder), {"name": "Jane Doe", "organization": "Ops Alpha", "email": "jane@example.org"})
        finally:
            conn.close()

    def test_import_updates_existing_holder_for_matching_email(self) -> None:
        original_org_id = self._insert_organization("Ops Alpha")
        self._insert_holder(
            name="Old Name",
            organization="Ops Alpha",
            organization_id=original_org_id,
            email="jane@example.org",
        )
        csv_path = self._write_csv(
            "holders.csv",
            "organization,name,email\nOps Bravo,New Name,jane@example.org\n",
        )

        report = holder_import.import_holders_csv(csv_path, db_path=self.db_path)

        self.assertEqual(report.summary(), {"processed": 1, "created": 0, "updated": 1, "errors": 0})
        conn = self._connection()
        try:
            holder = conn.execute(
                "SELECT name, organization, email FROM holders WHERE email = ?;",
                ("jane@example.org",),
            ).fetchone()
            self.assertIsNotNone(holder)
            self.assertEqual(dict(holder), {"name": "New Name", "organization": "Ops Bravo", "email": "jane@example.org"})

            org = conn.execute("SELECT name FROM organizations WHERE name = ?;", ("Ops Bravo",)).fetchone()
            self.assertIsNotNone(org)
        finally:
            conn.close()

    def test_import_rejects_blank_organization(self) -> None:
        csv_path = self._write_csv(
            "holders.csv",
            "organization,name,email\n,Jane Doe,jane@example.org\n",
        )

        report = holder_import.import_holders_csv(csv_path, db_path=self.db_path)

        self.assertEqual(report.summary(), {"processed": 1, "created": 0, "updated": 0, "errors": 1})
        self.assertEqual(report.errors, ("Row 2: organization is required",))

    def test_import_rejects_blank_name(self) -> None:
        csv_path = self._write_csv(
            "holders.csv",
            "organization,name,email\nOps Alpha,,jane@example.org\n",
        )

        report = holder_import.import_holders_csv(csv_path, db_path=self.db_path)

        self.assertEqual(report.summary(), {"processed": 1, "created": 0, "updated": 0, "errors": 1})
        self.assertEqual(report.errors, ("Row 2: name is required",))

    def test_import_rejects_blank_email(self) -> None:
        csv_path = self._write_csv(
            "holders.csv",
            "organization,name,email\nOps Alpha,Jane Doe,\n",
        )

        report = holder_import.import_holders_csv(csv_path, db_path=self.db_path)

        self.assertEqual(report.summary(), {"processed": 1, "created": 0, "updated": 0, "errors": 1})
        self.assertEqual(report.errors, ("Row 2: email is required",))

    def test_import_rejects_malformed_csv_rows(self) -> None:
        csv_path = self._write_csv(
            "holders.csv",
            "organization,name,email\nOps Alpha,Jane Doe,jane@example.org,unexpected\n",
        )

        report = holder_import.import_holders_csv(csv_path, db_path=self.db_path)

        self.assertEqual(report.summary(), {"processed": 0, "created": 0, "updated": 0, "errors": 1})
        self.assertEqual(report.errors, ("Row 2: malformed CSV row has extra columns.",))

    def test_cli_returns_summary_and_nonzero_exit_on_invalid_csv(self) -> None:
        csv_path = self._write_csv(
            "holders.csv",
            "organization,name,email\nOps Alpha,,jane@example.org\n",
        )

        exit_code = holder_import.main([str(csv_path), "--db", str(self.db_path)])

        self.assertEqual(exit_code, 2)
        report = holder_import.import_holders_csv(csv_path, db_path=self.db_path)
        self.assertEqual(json.dumps(report.summary(), sort_keys=True), "{\"created\": 0, \"errors\": 1, \"processed\": 1, \"updated\": 0}")

    def test_script_entrypoint_runs_end_to_end(self) -> None:
        csv_path = self._write_csv(
            "holders.csv",
            "organization,name,email\nOps Alpha,Jane Doe,jane@example.org\n",
        )
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "import_holders_csv.py"

        result = subprocess.run(
            [sys.executable, str(script_path), str(csv_path), "--db", str(self.db_path)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout.strip()),
            {"processed": 1, "created": 1, "updated": 0, "errors": 0},
        )


if __name__ == "__main__":
    unittest.main()
