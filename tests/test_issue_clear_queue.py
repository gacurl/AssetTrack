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


def test_operator_can_remove_one_queue_item_by_index_without_affecting_duplicates(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-remove-one", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True

    intake_app.SCAN_QUEUE.extend(
        [
            Scan.now("DUP-TAG"),
            Scan.now("DUP-TAG"),
            Scan.now("KEEP-TAG"),
        ]
    )

    response = client_with_temp_db.post(
        "/",
        data={"action": "remove", "queue_index": "1", "return_to": "/issue"},
    )

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/issue")
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["DUP-TAG", "KEEP-TAG"]

    issue_page = client_with_temp_db.get("/issue")
    assert issue_page.status_code == 200
    assert b"Queue (2)" in issue_page.data


def test_operator_can_clear_queue_from_issue_preview_and_return_to_issue(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-clear-preview", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True

    intake_app.SCAN_QUEUE.extend([Scan.now("TAG-1"), Scan.now("TAG-2")])

    preview_page = client_with_temp_db.get("/issue/preview")
    assert preview_page.status_code == 200
    assert b"Clear Queue" in preview_page.data

    response = client_with_temp_db.post(
        "/",
        data={"action": "clear", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert len(intake_app.SCAN_QUEUE) == 0
    assert b"Issuing Assets" in response.data
    assert b"Queue (0)" in response.data
    assert b"Queued assets:</strong> 0" in response.data


def test_issue_scan_normalizes_asset_tag_to_uppercase_and_blocks_case_variant_duplicate(
    client_with_temp_db,
) -> None:
    operator_id = create_test_user(username="operator-uppercase-issue", password="op-pass", role="operator")

    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True

    first = client_with_temp_db.post(
        "/",
        data={"scan_text": "ab-123", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert first.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["AB123"]
    assert b"AB123" in first.data
    assert b"ab-123" not in first.data

    second = client_with_temp_db.post(
        "/",
        data={"scan_text": "AB123", "return_to": "/issue"},
        follow_redirects=True,
    )

    assert second.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["AB123"]
    assert b"Asset AB123 is already queued." in second.data

    preview = client_with_temp_db.get("/issue/preview")
    assert preview.status_code == 200
    assert b"AB123" in preview.data
    assert b"ab-123" not in preview.data
