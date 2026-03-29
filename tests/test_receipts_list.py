from __future__ import annotations

import pytest

from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user
from tests.test_receipt_detail import (
    _create_issue_receipt,
    _create_return_receipt,
    _login_user,
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
    assert response.data.count(b'">Open</a>') == 1


def test_receipts_list_holder_name_search_returns_expected_receipt(client_with_temp_db) -> None:
    issue_receipt_id = _create_issue_receipt(client_with_temp_db)
    _create_return_receipt(client_with_temp_db)

    response = client_with_temp_db.get("/receipts?holder_name=Issue%20Holder")

    assert response.status_code == 200
    assert f'href="/receipts/{issue_receipt_id}"'.encode("utf-8") in response.data
    assert b"Issue Holder" in response.data
    assert response.data.count(b'">Open</a>') == 1


def test_receipts_list_building_room_search_returns_expected_receipt(client_with_temp_db) -> None:
    _create_issue_receipt(client_with_temp_db)
    mixed_return_receipt_id = _create_return_receipt(client_with_temp_db, mixed_holders=True)

    response = client_with_temp_db.get("/receipts?building_room=HQ%20North/211")

    assert response.status_code == 200
    assert f'href="/receipts/{mixed_return_receipt_id}"'.encode("utf-8") in response.data
    assert response.data.count(b'">Open</a>') == 1


def test_mixed_holder_return_renders_multiple_holders_summary(client_with_temp_db) -> None:
    mixed_return_receipt_id = _create_return_receipt(client_with_temp_db, mixed_holders=True)

    response = client_with_temp_db.get("/receipts")

    assert response.status_code == 200
    assert f'href="/receipts/{mixed_return_receipt_id}"'.encode("utf-8") in response.data
    assert b"Multiple holders" in response.data


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
    assert response.json == {"ok": False, "error": "Forbidden"}


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

    response = client_with_temp_db.get("/receipts")

    assert response.status_code == 200
    assert f'href="/receipts/{receipt_id}"'.encode("utf-8") in response.data

    detail_response = client_with_temp_db.get(f"/receipts/{receipt_id}")
    assert detail_response.status_code == 200


def test_receipts_list_building_room_search_matches_issue_location_summary(client_with_temp_db) -> None:
    issue_receipt_id = _create_issue_receipt(client_with_temp_db)
    _create_return_receipt(client_with_temp_db)

    response = client_with_temp_db.get("/receipts?building_room=HQ%20North/210")

    assert response.status_code == 200
    assert f'href="/receipts/{issue_receipt_id}"'.encode("utf-8") in response.data
