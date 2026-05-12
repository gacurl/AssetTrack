from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.intake.scan import Scan
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")

    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO holders (id, holder_type, name, identifier, contact_info, created_at, updated_at)
        VALUES (1, 'PERSON', 'Issue Holder', 'IH-1', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    intake_app.SCAN_QUEUE.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def test_issue_and_return_queue_pages_show_scan_timestamps(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-queue-ts", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"

    scan = Scan(
        asset_tag="QUEUE-TAG-1",
        scanned_at=datetime(2026, 1, 1, 14, 3, 22, tzinfo=timezone.utc),
        equipment_type="laptop",
    )
    intake_app.SCAN_QUEUE.append(scan)

    issue_page = client_with_temp_db.get("/issue")
    assert issue_page.status_code == 200
    assert b"14:03:22 UTC" in issue_page.data
    assert b"QUEUE-TAG-1" in issue_page.data

    with client_with_temp_db.session_transaction() as sess:
        sess["issue_mode"] = False

    return_page = client_with_temp_db.get("/return")
    assert return_page.status_code == 200
    assert b"14:03:22 UTC" in return_page.data
    assert b"QUEUE-TAG-1" in return_page.data
