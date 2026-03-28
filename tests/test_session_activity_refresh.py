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


def _login(client, monkeypatch: pytest.MonkeyPatch, *, last_seen: int = 100) -> int:
    user_id = create_test_user(username=f"user-{last_seen}", password="op-pass", role="operator")
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"
        sess["last_seen"] = last_seen
    return user_id


def test_authenticated_navigation_refreshes_last_seen(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _login(client_with_temp_db, monkeypatch, last_seen=100)
    monkeypatch.setattr(intake_app, "now_seconds", lambda: 200)

    response = client_with_temp_db.get("/dashboard")

    assert response.status_code == 200
    with client_with_temp_db.session_transaction() as sess:
        assert sess["last_seen"] == 200


def test_preview_load_refreshes_last_seen(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _login(client_with_temp_db, monkeypatch, last_seen=110)
    intake_app.SCAN_QUEUE.append(Scan.now("PREVIEW-TAG"))
    monkeypatch.setattr(intake_app, "now_seconds", lambda: 210)

    response = client_with_temp_db.get("/issue/preview")

    assert response.status_code == 200
    with client_with_temp_db.session_transaction() as sess:
        assert sess["last_seen"] == 210


def test_scan_submission_refreshes_last_seen(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _login(client_with_temp_db, monkeypatch, last_seen=120)
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO assets (asset_tag, location_type, current_holder_id, home_slot_id)
        VALUES ('SCAN-TAG-1', 'STORAGE', NULL, NULL);
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(intake_app, "now_seconds", lambda: 220)

    response = client_with_temp_db.post(
        "/",
        data={"scan_text": "SCAN-TAG-1", "return_to": "/issue"},
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/issue#queue-section")
    assert len(intake_app.SCAN_QUEUE) == 1
    with client_with_temp_db.session_transaction() as sess:
        assert sess["last_seen"] == 220


def test_queue_action_refreshes_last_seen(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _login(client_with_temp_db, monkeypatch, last_seen=130)
    intake_app.SCAN_QUEUE.append(Scan.now("CLEAR-ME"))
    monkeypatch.setattr(intake_app, "now_seconds", lambda: 230)

    response = client_with_temp_db.post(
        "/",
        data={"action": "clear", "return_to": "/issue"},
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/issue#queue-section")
    assert len(intake_app.SCAN_QUEUE) == 0
    with client_with_temp_db.session_transaction() as sess:
        assert sess["last_seen"] == 230


def test_public_unauthenticated_request_does_not_refresh_last_seen(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(intake_app, "now_seconds", lambda: 999)

    response = client_with_temp_db.get("/")

    assert response.status_code == 200
    with client_with_temp_db.session_transaction() as sess:
        assert "last_seen" not in sess
