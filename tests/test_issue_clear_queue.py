from __future__ import annotations

from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.intake.scan import Scan
from tests.auth_test_utils import create_test_user


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


def test_operator_clear_queue_from_issue_returns_to_issue(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-clear", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True

    intake_app.SCAN_QUEUE.append(Scan.now("UNKNOWN-TAG"))

    response = client_with_temp_db.post(
        "/",
        data={"action": "clear", "return_to": "/issue"},
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/issue")
    assert len(intake_app.SCAN_QUEUE) == 0

    issue_page = client_with_temp_db.get("/issue")
    assert issue_page.status_code == 200
    assert b"Queued assets:</strong> 0" in issue_page.data
