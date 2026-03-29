from __future__ import annotations

import json
from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")

    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO holders (id, holder_type, name, identifier, email, contact_info, created_at, updated_at)
        VALUES (1, 'PERSON', 'Issue Holder', 'IH-1', 'issue@example.org', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    intake_app.SCAN_QUEUE.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def _login_issue_operator(client, username: str) -> None:
    operator_id = create_test_user(username=username, password="op-pass", role="operator")
    with client.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"


def _insert_slot(conn, slot_id: int, case_name: str, slot_position: int) -> None:
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (?, ?, ?, NULL);
        """,
        (slot_id, case_name, slot_position),
    )


def _insert_asset(conn, asset_id: int, asset_tag: str, *, home_slot_id: int | None = None) -> None:
    conn.execute(
        """
        INSERT INTO assets (id, asset_tag, location_type, home_slot_id, current_holder_id)
        VALUES (?, ?, 'STORAGE', ?, NULL);
        """,
        (asset_id, asset_tag, home_slot_id),
    )


def _occupy_slot(conn, slot_id: int, asset_id: int) -> None:
    conn.execute(
        """
        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
        VALUES (?, ?, '2026-01-01T00:00:00Z');
        """,
        (slot_id, asset_id),
    )


def test_issue_case_scan_expands_expected_assets(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db, "operator-case-expand")

    conn = db.get_connection()
    _insert_slot(conn, 10, "CASE-2", 1)
    _insert_slot(conn, 11, "CASE-2", 2)
    _insert_slot(conn, 12, "CASE-2", 3)
    _insert_asset(conn, 100, "CI-100", home_slot_id=10)
    _insert_asset(conn, 101, "CI-101", home_slot_id=11)
    _occupy_slot(conn, 10, 100)
    _occupy_slot(conn, 11, 101)
    conn.commit()
    conn.close()

    response = client_with_temp_db.post(
        "/",
        data={"scan_text": "case-2", "return_to": "/issue#queue-section"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["CI100", "CI101"]
    assert b"Case CASE-2 added 2 assets to queue." in response.data
    assert b"Queue (2)" in response.data
    assert b"CASE2" not in response.data


def test_issue_case_scan_skips_already_queued_assets(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db, "operator-case-duplicate")

    conn = db.get_connection()
    _insert_slot(conn, 20, "CASE-20", 1)
    _insert_slot(conn, 21, "CASE-20", 2)
    _insert_asset(conn, 200, "CI-200", home_slot_id=20)
    _insert_asset(conn, 201, "CI-201", home_slot_id=21)
    _occupy_slot(conn, 20, 200)
    _occupy_slot(conn, 21, 201)
    conn.commit()
    conn.close()

    intake_app.SCAN_QUEUE.append(intake_app.Scan.now("CI200"))

    response = client_with_temp_db.post(
        "/",
        data={"scan_text": "CASE20", "return_to": "/issue#queue-section"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["CI200", "CI201"]
    assert b"Case CASE-20 added 1 asset to queue. Skipped 1 already queued." in response.data


def test_issue_case_scan_reports_empty_case(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db, "operator-case-empty")

    conn = db.get_connection()
    _insert_slot(conn, 30, "CASE-30", 1)
    _insert_slot(conn, 31, "CASE-30", 2)
    conn.commit()
    conn.close()

    response = client_with_temp_db.post(
        "/",
        data={"scan_text": "CASE-30", "return_to": "/issue#queue-section"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert len(intake_app.SCAN_QUEUE) == 0
    assert b"Case CASE-30 has no assets to add." in response.data


def test_issue_single_asset_scan_still_behaves_normally(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db, "operator-single-regression")

    conn = db.get_connection()
    _insert_asset(conn, 300, "SINGLE-300")
    conn.commit()
    conn.close()

    response = client_with_temp_db.post(
        "/",
        data={"scan_text": "single-300", "return_to": "/issue#queue-section"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["SINGLE300"]
    assert b"SINGLE300" in response.data


def test_issue_commit_after_case_scan_writes_one_event_per_asset(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db, "operator-case-commit")

    conn = db.get_connection()
    _insert_slot(conn, 40, "CASE-40", 1)
    _insert_slot(conn, 41, "CASE-40", 2)
    _insert_asset(conn, 400, "CI-400", home_slot_id=40)
    _insert_asset(conn, 401, "CI-401", home_slot_id=41)
    _occupy_slot(conn, 40, 400)
    _occupy_slot(conn, 41, 401)
    conn.commit()
    conn.close()

    scan_response = client_with_temp_db.post(
        "/",
        data={"scan_text": "CASE-40", "return_to": "/issue#queue-section"},
        follow_redirects=True,
    )
    assert scan_response.status_code == 200

    commit_response = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )

    assert commit_response.status_code == 302

    conn = db.get_connection()
    rows = conn.execute(
        """
        SELECT id, asset_tag, event_type, holder_id
        FROM asset_events
        WHERE event_type = 'ISSUE'
        ORDER BY asset_tag ASC;
        """
    ).fetchall()
    receipt_row = conn.execute(
        """
        SELECT id, receipt_type, holder_id, source_event_ids_json, snapshot_json, sent_at, last_attempt_at, last_error
        FROM receipt_queue
        ORDER BY id DESC
        LIMIT 1;
        """
    ).fetchone()
    asset_rows = conn.execute(
        """
        SELECT asset_tag, location_type, current_holder_id
        FROM assets
        WHERE id IN (400, 401)
        ORDER BY asset_tag ASC;
        """
    ).fetchall()
    conn.close()

    assert receipt_row is not None
    assert (commit_response.headers.get("Location") or "").endswith(f"/receipts/{int(receipt_row['id'])}")
    assert len(intake_app.SCAN_QUEUE) == 0
    assert [(str(row["asset_tag"]), str(row["event_type"]), int(row["holder_id"])) for row in rows] == [
        ("CI-400", "ISSUE", 1),
        ("CI-401", "ISSUE", 1),
    ]
    assert str(receipt_row["receipt_type"]) == "ISSUE"
    assert int(receipt_row["holder_id"]) == 1
    source_event_ids = json.loads(str(receipt_row["source_event_ids_json"]))
    assert source_event_ids == [int(rows[0]["id"]), int(rows[1]["id"])]
    receipt_snapshot = json.loads(str(receipt_row["snapshot_json"]))
    assert receipt_snapshot["source_event_ids"] == source_event_ids
    assert receipt_snapshot["delivery"]["state"] == "pending"
    assert receipt_snapshot["recipient_email"] == "issue@example.org"
    assert receipt_snapshot["holder_snapshot"]["email"] == "issue@example.org"
    assert len(receipt_snapshot["assets"]) == 2
    assert receipt_snapshot["assets"][0]["holder_snapshot"]["email"] == "issue@example.org"
    assert receipt_row["sent_at"] is None
    assert receipt_row["last_attempt_at"] is None
    assert receipt_row["last_error"] is None
    assert [(str(row["asset_tag"]), str(row["location_type"]), int(row["current_holder_id"])) for row in asset_rows] == [
        ("CI-400", "IN_CUSTODY", 1),
        ("CI-401", "IN_CUSTODY", 1),
    ]


def test_issue_case_scan_without_dash_also_expands_matching_case(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db, "operator-case-no-dash")

    conn = db.get_connection()
    _insert_slot(conn, 50, "CASE-2", 1)
    _insert_slot(conn, 51, "CASE-2", 2)
    _insert_asset(conn, 500, "CI-500", home_slot_id=50)
    _insert_asset(conn, 501, "CI-501", home_slot_id=51)
    _occupy_slot(conn, 50, 500)
    _occupy_slot(conn, 51, 501)
    conn.commit()
    conn.close()

    response = client_with_temp_db.post(
        "/",
        data={"scan_text": "CASE2", "return_to": "/issue#queue-section"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["CI500", "CI501"]
    assert b"Case CASE-2 added 2 assets to queue." in response.data


def test_invalid_case_scan_does_not_enqueue_pseudo_asset(client_with_temp_db) -> None:
    _login_issue_operator(client_with_temp_db, "operator-invalid-case")

    response = client_with_temp_db.post(
        "/",
        data={"scan_text": "CASE-404", "return_to": "/issue#queue-section"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert len(intake_app.SCAN_QUEUE) == 0
    assert b"CASE404" not in response.data
    assert b"Scan rejected. Asset tag not found in inventory." in response.data
