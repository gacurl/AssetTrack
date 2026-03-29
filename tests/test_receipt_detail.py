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
    intake_app.SCAN_QUEUE.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def _insert_holder(
    holder_id: int,
    *,
    name: str,
    identifier: str,
    organization: str = "",
    organization_id: int | None = None,
) -> None:
    conn = db.get_connection()
    try:
        if organization_id is not None:
            conn.execute(
                """
                INSERT INTO organizations (id, name, created_at, updated_at)
                VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
                """,
                (organization_id, organization or f"Organization {organization_id}"),
            )
        conn.execute(
            """
            INSERT INTO holders (
                id, holder_type, name, organization, organization_id, identifier, contact_info, created_at, updated_at
            )
            VALUES (?, 'PERSON', ?, ?, ?, ?, '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """,
            (holder_id, name, organization, organization_id, identifier),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_slot(slot_id: int, case_name: str, slot_position: int) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (?, ?, ?, NULL);
            """,
            (slot_id, case_name, slot_position),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_asset(
    asset_id: int,
    asset_tag: str,
    *,
    location_type: str,
    home_slot_id: int | None,
    current_holder_id: int | None = None,
    building_room: str = "",
    serial_number: str = "",
    equipment_type: str = "",
    manufacturer: str = "",
    model: str = "",
    model_code: str = "",
    notes: str = "",
) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO assets (
                id, asset_tag, serial_number, equipment_type, manufacturer, model, model_code, notes,
                location_type, current_holder_id, home_slot_id, building_room
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                asset_id,
                asset_tag,
                serial_number,
                equipment_type,
                manufacturer,
                model,
                model_code,
                notes,
                location_type,
                current_holder_id,
                home_slot_id,
                building_room,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _occupy_slot(slot_id: int, asset_id: int) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (?, ?, '2026-01-01T00:00:00Z');
            """,
            (slot_id, asset_id),
        )
        conn.commit()
    finally:
        conn.close()


def _login_issue_operator(client, *, username: str = "issue-operator") -> int:
    operator_id = create_test_user(username=username, password="op-pass", role="operator")
    with client.session_transaction() as sess:
        sess["user_id"] = operator_id
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"
    return operator_id


def _login_user(client, *, username: str, role: str) -> int:
    user_id = create_test_user(username=username, password="op-pass", role=role)
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    return user_id


def _latest_receipt_id() -> int:
    conn = db.get_connection()
    try:
        row = conn.execute(
            """
            SELECT id
            FROM receipt_queue
            ORDER BY id DESC
            LIMIT 1;
            """
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return int(row["id"])


def _create_issue_receipt(client) -> int:
    _insert_holder(1, name="Issue Holder", identifier="IH-1", organization="Operations", organization_id=9)
    _insert_slot(10, "CASE-10", 1)
    _insert_asset(
        100,
        "ISSUE-100",
        location_type="STORAGE",
        home_slot_id=10,
        building_room="Storage/A1",
        serial_number="SN-ISSUE-100",
        equipment_type="Laptop",
        manufacturer="Dell",
        model="Latitude",
        model_code="LAT-14",
        notes="Original issue note",
    )
    _occupy_slot(10, 100)
    _login_issue_operator(client)

    intake_app.SCAN_QUEUE.clear()
    intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="ISSUE-100", equipment_type="laptop"))

    response = client.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    return _latest_receipt_id()


def _create_return_receipt(client, *, mixed_holders: bool = False) -> int:
    _insert_holder(7, name="Return Holder One", identifier="RH-7")
    _insert_holder(8, name="Return Holder Two", identifier="RH-8")
    _insert_slot(20, "CASE-20", 1)
    _insert_slot(21, "CASE-20", 2)
    _insert_asset(
        200,
        "RETURN-200",
        location_type="IN_CUSTODY",
        current_holder_id=7,
        home_slot_id=20,
        building_room="HQ North/210",
        serial_number="SN-RETURN-200",
        equipment_type="Tablet",
        manufacturer="Apple",
        model="iPad",
        model_code="IP-1",
        notes="Return note one",
    )
    if mixed_holders:
        _insert_asset(
            201,
            "RETURN-201",
            location_type="IN_CUSTODY",
            current_holder_id=8,
            home_slot_id=21,
            building_room="HQ North/211",
            serial_number="SN-RETURN-201",
            equipment_type="Laptop",
            manufacturer="Lenovo",
            model="ThinkPad",
            model_code="TP-2",
            notes="Return note two",
        )
    _login_user(client, username="return-operator", role="operator")

    intake_app.SCAN_QUEUE.clear()
    intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="RETURN-200", equipment_type="tablet"))
    if mixed_holders:
        intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="RETURN-201", equipment_type="laptop"))

    response = client.post(
        "/return/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    return _latest_receipt_id()


def test_issue_receipt_detail_renders_from_snapshot(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200
    assert b"Receipt Detail" in response.data
    assert f"Receipt {receipt_id}".encode("utf-8") in response.data
    assert b"Receipt key:" in response.data
    assert b"ISSUE:" in response.data
    assert b"Receipt type:</strong> ISSUE" in response.data
    assert b"Committed by:</strong>" in response.data
    assert b"issue-operator" in response.data
    assert b"Receipt holder:</strong>" in response.data
    assert b"Issue Holder" in response.data
    assert b"Issue Location" in response.data
    assert b"HQ North" in response.data
    assert b"210" in response.data
    assert b"HQ North/210" in response.data
    assert b"ISSUE-100" in response.data
    assert b"Dell" in response.data
    assert b"Latitude" in response.data
    assert b"CASE-10 / 1" in response.data
    assert b"Source Events" in response.data


def test_return_receipt_detail_renders_from_snapshot(client_with_temp_db) -> None:
    receipt_id = _create_return_receipt(client_with_temp_db)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200
    assert b"Receipt type:</strong> RETURN" in response.data
    assert b"RETURN:" in response.data
    assert b"Return Holder One" in response.data
    assert b"RETURN-200" in response.data
    assert b"Apple" in response.data
    assert b"iPad" in response.data
    assert b"CASE-20 / 1" in response.data
    assert b"Source Events" in response.data


def test_receipt_detail_shows_delivery_state_from_persisted_queue_metadata(client_with_temp_db) -> None:
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
        snapshot["delivery"] = {
            "state": "pending",
            "sent_at": None,
            "last_attempt_at": "2026-03-29T12:00:00+00:00",
            "last_error": "smtp offline",
        }
        conn.execute(
            """
            UPDATE receipt_queue
            SET snapshot_json = ?, sent_at = NULL, last_attempt_at = ?, last_error = ?
            WHERE id = ?;
            """,
            (
                json.dumps(snapshot, sort_keys=True),
                "2026-03-29T12:00:00+00:00",
                "smtp offline",
                receipt_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    failed_response = client_with_temp_db.get(f"/receipts/{receipt_id}")
    assert failed_response.status_code == 200
    assert b"Delivery state:</strong>" in failed_response.data
    assert b">failed<" in failed_response.data
    assert b"Last delivery attempt:</strong> 2026-03-29T12:00:00+00:00" in failed_response.data
    assert b"Last delivery error:</strong> smtp offline" in failed_response.data

    conn = db.get_connection()
    try:
        conn.execute(
            """
            UPDATE receipt_queue
            SET sent_at = ?, last_attempt_at = ?, last_error = NULL
            WHERE id = ?;
            """,
            (
                "2026-03-29T12:05:00+00:00",
                "2026-03-29T12:04:00+00:00",
                receipt_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    sent_response = client_with_temp_db.get(f"/receipts/{receipt_id}")
    assert sent_response.status_code == 200
    assert b">sent<" in sent_response.data
    assert b"Delivered at:</strong> 2026-03-29T12:05:00+00:00" in sent_response.data


def test_receipt_detail_hides_delivery_state_for_historical_nonqueued_receipt(client_with_temp_db) -> None:
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

    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200
    assert b"Delivery state:</strong>" not in response.data
    assert b">pending<" not in response.data


def test_mixed_holder_return_renders_safely(client_with_temp_db) -> None:
    receipt_id = _create_return_receipt(client_with_temp_db, mixed_holders=True)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200
    assert b"Receipt type:</strong> RETURN" in response.data
    assert b"Receipt holder:" not in response.data
    assert b"Return Holder One" in response.data
    assert b"Return Holder Two" in response.data
    assert b"RETURN-200" in response.data
    assert b"RETURN-201" in response.data


def test_missing_receipt_returns_404(client_with_temp_db) -> None:
    operator_id = create_test_user(username="missing-operator", password="op-pass", role="operator")
    with client_with_temp_db.session_transaction() as sess:
        sess["user_id"] = operator_id

    response = client_with_temp_db.get("/receipts/9999")

    assert response.status_code == 404


@pytest.mark.parametrize("role", ["operator", "admin"])
def test_receipt_detail_allows_operator_and_admin(client_with_temp_db, role: str) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    _login_user(client_with_temp_db, username=f"{role}-viewer", role=role)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200


def test_receipt_detail_requires_login(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    with client_with_temp_db.session_transaction() as sess:
        sess.clear()

    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 403
    assert response.json == {"ok": False, "error": "Forbidden"}


def test_receipt_detail_timeout_matches_existing_readonly_pattern(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    _login_user(client_with_temp_db, username="timeout-operator", role="operator")
    monkeypatch.setattr(intake_app, "auth_enabled", lambda: True)
    monkeypatch.setattr(intake_app, "enforce_inactivity_timeout", lambda: False)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}", follow_redirects=False)

    assert response.status_code == 302
    assert (response.headers.get("Location") or "").endswith("/")


def test_receipt_detail_uses_snapshot_truth_not_live_tables(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)

    conn = db.get_connection()
    try:
        conn.execute(
            """
            UPDATE holders
            SET name = ?, identifier = ?
            WHERE id = 1;
            """,
            ("Mutated Holder", "IH-CHANGED"),
        )
        conn.execute(
            """
            UPDATE assets
            SET manufacturer = ?, model = ?, notes = ?
            WHERE id = 100;
            """,
            ("Changed Maker", "Changed Model", "Changed note"),
        )
        conn.execute(
            """
            UPDATE users
            SET username = ?
            WHERE username = ?;
            """,
            ("mutated-operator", "issue-operator"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200
    assert b"Issue Holder" in response.data
    assert b"IH-1" in response.data
    assert b"Dell" in response.data
    assert b"Latitude" in response.data
    assert b"issue-operator" in response.data
    assert b"Mutated Holder" not in response.data
    assert b"IH-CHANGED" not in response.data
    assert b"Changed Maker" not in response.data
    assert b"Changed Model" not in response.data
    assert b"mutated-operator" not in response.data
