from __future__ import annotations

import assettrack.db as db
import json
import pytest

from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user
from tests.test_receipt_detail import (
    _create_issue_receipt,
    _create_return_receipt,
    _login_user,
    _stored_receipt_display_title,
    client_with_temp_db,
)


def test_receipts_list_renders_newest_first(client_with_temp_db) -> None:
    older_receipt_id = _create_issue_receipt(client_with_temp_db)
    newer_receipt_id = _create_return_receipt(client_with_temp_db)

    response = client_with_temp_db.get("/receipts")

    assert response.status_code == 200
    assert response.data.find(f"/receipts/{newer_receipt_id}".encode("utf-8")) < response.data.find(
        f"/receipts/{older_receipt_id}".encode("utf-8")
    )


def test_receipts_list_asset_tag_search_returns_expected_receipt(client_with_temp_db) -> None:
    _create_issue_receipt(client_with_temp_db)
    return_receipt_id = _create_return_receipt(client_with_temp_db)

    response = client_with_temp_db.get("/receipts?asset_tag=RETURN-200")

    assert response.status_code == 200
    assert f'href="/receipts/{return_receipt_id}"'.encode("utf-8") in response.data
    assert b"Matched asset tag" in response.data
    assert b"Asset tag search match" in response.data
    assert b"RETURN-200" in response.data
    assert response.data.count(b'href="/receipts/') == 1


def test_receipts_list_holder_name_search_returns_expected_receipt(client_with_temp_db) -> None:
    issue_receipt_id = _create_issue_receipt(client_with_temp_db)
    _create_return_receipt(client_with_temp_db)

    response = client_with_temp_db.get("/receipts?holder_name=Issue%20Holder")

    assert response.status_code == 200
    assert f'href="/receipts/{issue_receipt_id}"'.encode("utf-8") in response.data
    assert b"Issue Holder" in response.data
    assert b"Holder search match" in response.data
    assert response.data.count(b'href="/receipts/') == 1


def test_receipts_list_building_room_search_returns_expected_receipt(client_with_temp_db) -> None:
    _create_issue_receipt(client_with_temp_db)
    mixed_return_receipt_id = _create_return_receipt(client_with_temp_db, mixed_holders=True)

    response = client_with_temp_db.get("/receipts?building_room=HQ%20North/211")

    assert response.status_code == 200
    assert f'href="/receipts/{mixed_return_receipt_id}"'.encode("utf-8") in response.data
    assert b"Location search match" in response.data
    assert b"HQ North/211" in response.data
    assert response.data.count(b'href="/receipts/') == 1


def test_mixed_holder_return_renders_multiple_holders_summary(client_with_temp_db) -> None:
    mixed_return_receipt_id = _create_return_receipt(client_with_temp_db, mixed_holders=True)
    expected_title = _stored_receipt_display_title(mixed_return_receipt_id)

    response = client_with_temp_db.get("/receipts")

    assert response.status_code == 200
    assert f'href="/receipts/{mixed_return_receipt_id}"'.encode("utf-8") in response.data
    assert expected_title.encode("utf-8") in response.data
    assert b"Multiple holders" in response.data
    assert b"Return location varies by asset" in response.data


def test_receipts_list_shows_asset_tag_in_default_results(client_with_temp_db) -> None:
    _create_issue_receipt(client_with_temp_db)

    response = client_with_temp_db.get("/receipts")

    assert response.status_code == 200
    assert b"Asset Tag" in response.data
    assert b"ISSUE-100" in response.data
    assert b">Queued<" in response.data


def test_receipts_list_shows_failed_delivery_state_from_persisted_queue_metadata(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)

    conn = db.get_connection()
    try:
        conn.execute(
            """
            UPDATE receipt_queue
            SET last_attempt_at = ?, last_error = ?
            WHERE id = ?;
            """,
            (
                "2026-03-29T12:00:00+00:00",
                "smtp offline",
                receipt_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.get("/receipts")

    assert response.status_code == 200
    assert f'href="/receipts/{receipt_id}"'.encode("utf-8") in response.data
    assert b">failed<" in response.data


def test_receipts_list_hides_delivery_state_for_historical_nonqueued_receipt(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)

    conn = db.get_connection()
    try:
        row = conn.execute(
            """
            SELECT snapshot_json
            FROM receipt_queue
            WHERE id = ?;
            """,
            (receipt_id,),
        ).fetchone()
        assert row is not None
        snapshot = json.loads(str(row["snapshot_json"]))
        snapshot.pop("delivery", None)
        conn.execute(
            """
            UPDATE receipt_queue
            SET snapshot_json = ?, sent_at = NULL, last_attempt_at = NULL, last_error = NULL
            WHERE id = ?;
            """,
            (
                json.dumps(snapshot, sort_keys=True),
                receipt_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.get("/receipts")

    assert response.status_code == 200
    assert f'href="/receipts/{receipt_id}"'.encode("utf-8") in response.data
    assert b">pending<" not in response.data
    assert b">sent<" not in response.data
    assert b">failed<" not in response.data


def test_receipts_list_renders_clear_search_link_when_filters_are_active(client_with_temp_db) -> None:
    _create_issue_receipt(client_with_temp_db)

    response = client_with_temp_db.get("/receipts?holder_name=Issue%20Holder")

    assert response.status_code == 200
    assert b'href="/receipts"' in response.data
    assert b"Clear search" in response.data


@pytest.mark.parametrize("role", ["operator", "admin"])
def test_receipts_list_allows_operator_and_admin(client_with_temp_db, role: str) -> None:
    _create_issue_receipt(client_with_temp_db)
    _login_user(client_with_temp_db, username=f"{role}-list-viewer", role=role)

    response = client_with_temp_db.get("/receipts")

    assert response.status_code == 200


def test_receipts_list_requires_login(client_with_temp_db) -> None:
    _create_issue_receipt(client_with_temp_db)
    with client_with_temp_db.session_transaction() as sess:
        sess.clear()

    response = client_with_temp_db.get("/receipts")

    assert response.status_code == 403
    assert b"Access Not Allowed" in response.data


def test_receipts_list_timeout_matches_existing_readonly_pattern(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_issue_receipt(client_with_temp_db)
    _login_user(client_with_temp_db, username="timeout-list-operator", role="operator")
    monkeypatch.setattr(intake_app, "auth_enabled", lambda: True)
    monkeypatch.setattr(intake_app, "enforce_inactivity_timeout", lambda: False)

    response = client_with_temp_db.get("/receipts", follow_redirects=False)

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/")


def test_receipts_list_links_to_existing_receipt_detail(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    expected_title = _stored_receipt_display_title(receipt_id)

    response = client_with_temp_db.get("/receipts")

    assert response.status_code == 200
    assert f'href="/receipts/{receipt_id}"'.encode("utf-8") in response.data
    assert expected_title.encode("utf-8") in response.data
    assert b"Internal receipt ID" not in response.data
    assert b"Detail" not in response.data

    detail_response = client_with_temp_db.get(f"/receipts/{receipt_id}")
    assert detail_response.status_code == 200


def test_receipts_list_renders_distinct_issue_and_return_titles(client_with_temp_db) -> None:
    issue_receipt_id = _create_issue_receipt(client_with_temp_db)
    return_receipt_id = _create_return_receipt(client_with_temp_db)
    issue_title = _stored_receipt_display_title(issue_receipt_id)
    return_title = _stored_receipt_display_title(return_receipt_id)

    response = client_with_temp_db.get("/receipts")

    assert response.status_code == 200
    assert issue_title.encode("utf-8") in response.data
    assert return_title.encode("utf-8") in response.data


def test_receipts_list_uses_stable_holder_fallback_when_snapshot_name_is_missing(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)

    conn = db.get_connection()
    try:
        row = conn.execute(
            """
            SELECT snapshot_json
            FROM receipt_queue
            WHERE id = ?;
            """,
            (receipt_id,),
        ).fetchone()
        assert row is not None
        snapshot = json.loads(str(row["snapshot_json"]))
        snapshot["holder_snapshot"]["name"] = ""
        snapshot["assets"][0]["holder_snapshot"]["name"] = ""
        conn.execute(
            """
            UPDATE receipt_queue
            SET snapshot_json = ?
            WHERE id = ?;
            """,
            (
                json.dumps(snapshot, sort_keys=True),
                receipt_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    expected_title = _stored_receipt_display_title(receipt_id)
    response = client_with_temp_db.get("/receipts")

    assert response.status_code == 200
    assert expected_title.encode("utf-8") in response.data


def test_receipts_list_building_room_search_matches_issue_location_summary(client_with_temp_db) -> None:
    issue_receipt_id = _create_issue_receipt(client_with_temp_db)
    _create_return_receipt(client_with_temp_db)

    response = client_with_temp_db.get("/receipts?building_room=HQ%20North/210")

    assert response.status_code == 200
    assert f'href="/receipts/{issue_receipt_id}"'.encode("utf-8") in response.data
    assert b"Location search match" in response.data
    assert b"HQ North/210" in response.data
