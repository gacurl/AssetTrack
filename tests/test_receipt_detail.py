from __future__ import annotations

import json
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

import assettrack.db as db
from assettrack.intake import app as intake_app
from assettrack.settings import write_receipt_cc_setting
from tests.auth_test_utils import create_test_user, login_session


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
    email: str = "",
    contact_info: str = "",
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
                id, holder_type, name, organization, organization_id, identifier, email, contact_info, created_at, updated_at
            )
            VALUES (?, 'PERSON', ?, ?, ?, ?, ?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """,
            (holder_id, name, organization, organization_id, identifier, email, contact_info),
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
    login_session(client, operator_id)
    with client.session_transaction() as sess:
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"
    return operator_id


def _login_user(client, *, username: str, role: str) -> int:
    user_id = create_test_user(username=username, password="op-pass", role=role)
    login_session(client, user_id)
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


def _receipt_row(receipt_id: int):
    conn = db.get_connection()
    try:
        row = conn.execute(
            """
            SELECT commit_at, snapshot_json
            FROM receipt_queue
            WHERE id = ?;
            """,
            (receipt_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return row


def _stored_receipt_display_title(receipt_id: int) -> str:
    row = _receipt_row(receipt_id)
    snapshot = json.loads(str(row["snapshot_json"]))
    receipt = intake_app._receipt_from_queue_row(
        {
            "id": receipt_id,
            "receipt_key": "",
            "receipt_type": snapshot.get("receipt_type", ""),
            "source_event_ids_json": json.dumps(snapshot.get("source_event_ids", [])),
            "snapshot_json": row["snapshot_json"],
            "commit_at": row["commit_at"],
            "commit_operator_user_id": snapshot.get("commit_operator_user_id", 0),
            "holder_id": snapshot.get("holder_id"),
            "sent_at": None,
            "last_attempt_at": None,
            "last_error": None,
        }
    )
    return str(receipt["display_title"])


def _stored_receipt_download_name(receipt_id: int) -> str:
    row = _receipt_row(receipt_id)
    snapshot = json.loads(str(row["snapshot_json"]))
    receipt = intake_app._receipt_from_queue_row(
        {
            "id": receipt_id,
            "receipt_key": "",
            "receipt_type": snapshot.get("receipt_type", ""),
            "source_event_ids_json": json.dumps(snapshot.get("source_event_ids", [])),
            "snapshot_json": row["snapshot_json"],
            "commit_at": row["commit_at"],
            "commit_operator_user_id": snapshot.get("commit_operator_user_id", 0),
            "holder_id": snapshot.get("holder_id"),
            "sent_at": None,
            "last_attempt_at": None,
            "last_error": None,
        }
    )
    return intake_app._receipt_pdf_download_name(receipt)


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _create_issue_receipt(client) -> int:
    _insert_holder(
        1,
        name="Issue Holder",
        identifier="IH-1",
        organization="Operations",
        organization_id=9,
        email="issue@example.org",
    )
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
    _insert_holder(7, name="Return Holder One", identifier="RH-7", email="return.one@example.org")
    _insert_holder(8, name="Return Holder Two", identifier="RH-8", email="return.two@example.org")
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
    expected_title = _stored_receipt_display_title(receipt_id)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200
    assert b"Issue Receipt" in response.data
    assert expected_title.encode("utf-8") in response.data
    assert b"Internal receipt ID" in response.data
    assert f">{receipt_id}<".encode("utf-8") in response.data
    assert b"Receipt key" in response.data
    assert b"ISSUE:" in response.data
    assert b"What Happened" in response.data
    assert b"Committed by" in response.data
    assert b"issue-operator" in response.data
    assert b"Receipt holder" in response.data
    assert b"Issue Holder" in response.data
    assert b"issue@example.org" in response.data
    assert b"Issue Location" in response.data
    assert b"HQ North" in response.data
    assert b"210" in response.data
    assert b"HQ North/210" in response.data
    assert b"ISSUE-100" in response.data
    assert b"Dell" in response.data
    assert b"Latitude" in response.data
    assert b"CASE-10 / 1" in response.data


def test_return_receipt_detail_renders_from_snapshot(client_with_temp_db) -> None:
    receipt_id = _create_return_receipt(client_with_temp_db)
    expected_title = _stored_receipt_display_title(receipt_id)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200
    assert b"Return Receipt" in response.data
    assert expected_title.encode("utf-8") in response.data
    assert b"RETURN:" in response.data
    assert b"Return Holder One" in response.data
    assert b"return.one@example.org" in response.data
    assert b"RETURN-200" in response.data
    assert b"Apple" in response.data
    assert b"iPad" in response.data
    assert b"CASE-20 / 1" in response.data


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
    assert b"Receipt email status" in failed_response.data
    assert b">failed<" in failed_response.data
    assert b"Retry Send" in failed_response.data
    assert b"Send Receipt Email" not in failed_response.data
    assert b"Last attempted" in failed_response.data
    assert b"Mar 29, 2026 at 12:00 UTC" in failed_response.data
    assert b"Current issue" in failed_response.data
    assert b"smtp offline" in failed_response.data

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
    assert b"Retry Send" not in sent_response.data
    assert b"Send Receipt Email" not in sent_response.data
    assert b"Delivered" in sent_response.data
    assert b"Mar 29, 2026 at 12:05 UTC" in sent_response.data


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
    assert b"Receipt email status" not in response.data
    assert b"Retry Send" not in response.data
    assert b"Send Receipt Email" not in response.data
    assert b">pending<" not in response.data


def test_mixed_holder_return_renders_safely(client_with_temp_db) -> None:
    receipt_id = _create_return_receipt(client_with_temp_db, mixed_holders=True)
    expected_title = _stored_receipt_display_title(receipt_id)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200
    assert b"What Happened" in response.data
    assert expected_title.encode("utf-8") in response.data
    assert b"Receipt holder" not in response.data
    assert b"Return Holder One" in response.data
    assert b"Return Holder Two" in response.data
    assert b"RETURN-200" in response.data
    assert b"RETURN-201" in response.data


def test_missing_receipt_returns_404(client_with_temp_db) -> None:
    operator_id = create_test_user(username="missing-operator", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

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
    assert b"Access Not Allowed" in response.data


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


def test_receipt_detail_links_to_receipt_pdf(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200
    assert f'href="/receipts/{receipt_id}/pdf"'.encode("utf-8") in response.data
    assert b"Download Receipt PDF" in response.data


def test_receipt_detail_uses_stable_holder_fallback_when_snapshot_name_is_missing(client_with_temp_db) -> None:
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
        asset_holder = snapshot["assets"][0]["holder_snapshot"]
        asset_holder["name"] = ""
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
    response = client_with_temp_db.get(f"/receipts/{receipt_id}")

    assert response.status_code == 200
    assert expected_title.encode("utf-8") in response.data


def test_issue_receipt_snapshot_stores_holder_email(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)

    conn = db.get_connection()
    try:
        row = conn.execute("SELECT snapshot_json FROM receipt_queue WHERE id = ?;", (receipt_id,)).fetchone()
    finally:
        conn.close()

    assert row is not None
    snapshot = json.loads(str(row["snapshot_json"]))
    assert snapshot["recipient_email"] == "issue@example.org"
    assert snapshot["holder_snapshot"]["email"] == "issue@example.org"
    assert snapshot["assets"][0]["holder_snapshot"]["email"] == "issue@example.org"


def test_return_receipt_snapshot_stores_unique_holder_email(client_with_temp_db) -> None:
    receipt_id = _create_return_receipt(client_with_temp_db)

    conn = db.get_connection()
    try:
        row = conn.execute("SELECT snapshot_json FROM receipt_queue WHERE id = ?;", (receipt_id,)).fetchone()
    finally:
        conn.close()

    assert row is not None
    snapshot = json.loads(str(row["snapshot_json"]))
    assert snapshot["recipient_email"] == "return.one@example.org"
    assert snapshot["holder_snapshot"]["email"] == "return.one@example.org"
    assert snapshot["assets"][0]["from_holder_snapshot"]["email"] == "return.one@example.org"


def test_mixed_holder_return_snapshot_keeps_recipient_email_blank(client_with_temp_db) -> None:
    receipt_id = _create_return_receipt(client_with_temp_db, mixed_holders=True)

    conn = db.get_connection()
    try:
        row = conn.execute("SELECT snapshot_json FROM receipt_queue WHERE id = ?;", (receipt_id,)).fetchone()
    finally:
        conn.close()

    assert row is not None
    snapshot = json.loads(str(row["snapshot_json"]))
    assert snapshot["holder_id"] is None
    assert snapshot["recipient_email"] == ""


def test_issue_receipt_pdf_download_uses_stored_snapshot_data(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    expected_download_name = _stored_receipt_download_name(receipt_id)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}/pdf")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    disposition = response.headers.get("Content-Disposition") or ""
    assert "attachment;" in disposition
    assert expected_download_name in disposition

    pdf_text = _extract_pdf_text(response.data)
    assert "Issue Receipt" in pdf_text
    assert "1 asset issued to Issue Holder" in pdf_text
    assert "Receipt delivery queued. Custody is already recorded." in pdf_text
    assert "What Happened" in pdf_text
    assert "Action" in pdf_text
    assert "Assets in this receipt" in pdf_text
    assert "Organization" in pdf_text
    assert "Operations" in pdf_text
    assert "Location" in pdf_text
    assert "HQ North/210" in pdf_text
    assert "Audit Details" in pdf_text
    assert "Receipt ID" in pdf_text
    assert str(receipt_id) in pdf_text
    assert "Typed name" in pdf_text
    assert "Initials" in pdf_text
    assert "ISSUE-100" in pdf_text
    assert "Dell / Latitude (LAT-14)" in pdf_text
    assert "IN CUSTODY" in pdf_text
    assert "IN_CUSTODY" not in pdf_text


def test_return_receipt_pdf_download_uses_human_readable_filename(client_with_temp_db) -> None:
    receipt_id = _create_return_receipt(client_with_temp_db)
    expected_download_name = _stored_receipt_download_name(receipt_id)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}/pdf")

    assert response.status_code == 200
    disposition = response.headers.get("Content-Disposition") or ""
    assert "attachment;" in disposition
    assert expected_download_name in disposition


def test_receipt_send_success_updates_delivery_state(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _insert_holder(
        1,
        name="Issue Holder",
        identifier="IH-1",
        organization="Operations",
        organization_id=9,
        email="issue@example.org",
    )
    _insert_slot(10, "CASE-10", 1)
    _insert_asset(100, "ISSUE-100", location_type="STORAGE", home_slot_id=10, building_room="Storage/A1")
    _occupy_slot(10, 100)
    _login_issue_operator(client_with_temp_db)
    intake_app.SCAN_QUEUE.clear()
    intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="ISSUE-100", equipment_type="laptop"))
    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )
    assert commit.status_code == 302
    receipt_id = _latest_receipt_id()

    sent_receipts: list[int] = []

    def _fake_send(receipt: dict[str, object]) -> list[str]:
        sent_receipts.append(int(receipt["id"]))
        return ["issue@example.org"]

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    response = client_with_temp_db.post(f"/receipts/{receipt_id}/send?json=1")

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert int(response.json["receipt_id"]) == receipt_id
    assert response.json["recipients"] == ["issue@example.org"]
    assert sent_receipts == [receipt_id]

    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT sent_at, last_attempt_at, last_error FROM receipt_queue WHERE id = ?;",
            (receipt_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["sent_at"] is not None
    assert row["last_attempt_at"] is not None
    assert row["last_error"] is None


def test_receipt_send_failure_updates_delivery_state(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _insert_holder(
        1,
        name="Issue Holder",
        identifier="IH-1",
        organization="Operations",
        organization_id=9,
        email="issue@example.org",
    )
    _insert_slot(10, "CASE-10", 1)
    _insert_asset(100, "ISSUE-100", location_type="STORAGE", home_slot_id=10, building_room="Storage/A1")
    _occupy_slot(10, 100)
    _login_issue_operator(client_with_temp_db)
    intake_app.SCAN_QUEUE.clear()
    intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="ISSUE-100", equipment_type="laptop"))
    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )
    assert commit.status_code == 302
    receipt_id = _latest_receipt_id()

    def _fake_send(_receipt: dict[str, object]) -> list[str]:
        raise RuntimeError("smtp offline")

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    response = client_with_temp_db.post(f"/receipts/{receipt_id}/send?json=1")

    assert response.status_code == 500
    assert response.json == {"ok": False, "error": "smtp offline"}

    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT sent_at, last_attempt_at, last_error FROM receipt_queue WHERE id = ?;",
            (receipt_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["sent_at"] is None
    assert row["last_attempt_at"] is not None
    assert row["last_error"] == "smtp offline"


def test_receipt_send_retry_after_failure_uses_existing_send_route(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _insert_holder(
        1,
        name="Issue Holder",
        identifier="IH-1",
        organization="Operations",
        organization_id=9,
        email="issue@example.org",
    )
    _insert_slot(10, "CASE-10", 1)
    _insert_asset(100, "ISSUE-100", location_type="STORAGE", home_slot_id=10, building_room="Storage/A1")
    _occupy_slot(10, 100)
    _login_issue_operator(client_with_temp_db)
    intake_app.SCAN_QUEUE.clear()
    intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="ISSUE-100", equipment_type="laptop"))
    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )
    assert commit.status_code == 302
    receipt_id = _latest_receipt_id()

    send_attempts: list[int] = []

    def _fake_send(receipt: dict[str, object]) -> list[str]:
        send_attempts.append(int(receipt["id"]))
        if len(send_attempts) == 1:
            raise RuntimeError("smtp offline")
        return ["issue@example.org"]

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    first = client_with_temp_db.post(f"/receipts/{receipt_id}/send?json=1")
    second = client_with_temp_db.post(f"/receipts/{receipt_id}/send?json=1")

    assert first.status_code == 500
    assert first.json == {"ok": False, "error": "smtp offline"}
    assert second.status_code == 200
    assert second.json["ok"] is True
    assert int(second.json["receipt_id"]) == receipt_id
    assert second.json["recipients"] == ["issue@example.org"]
    assert send_attempts == [receipt_id, receipt_id]

    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT sent_at, last_attempt_at, last_error FROM receipt_queue WHERE id = ?;",
            (receipt_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["sent_at"] is not None
    assert row["last_attempt_at"] is not None
    assert row["last_error"] is None


def test_receipt_send_failed_retry_remains_recoverable_after_repeated_failure(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _insert_holder(
        1,
        name="Issue Holder",
        identifier="IH-1",
        organization="Operations",
        organization_id=9,
        email="issue@example.org",
    )
    _insert_slot(10, "CASE-10", 1)
    _insert_asset(100, "ISSUE-100", location_type="STORAGE", home_slot_id=10, building_room="Storage/A1")
    _occupy_slot(10, 100)
    _login_issue_operator(client_with_temp_db)
    intake_app.SCAN_QUEUE.clear()
    intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="ISSUE-100", equipment_type="laptop"))
    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )
    assert commit.status_code == 302
    receipt_id = _latest_receipt_id()

    send_attempts: list[int] = []

    def _fake_send(receipt: dict[str, object]) -> list[str]:
        send_attempts.append(int(receipt["id"]))
        raise RuntimeError("smtp offline")

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    first = client_with_temp_db.post(f"/receipts/{receipt_id}/send?json=1")
    second = client_with_temp_db.post(f"/receipts/{receipt_id}/send?json=1")

    assert first.status_code == 500
    assert first.json == {"ok": False, "error": "smtp offline"}
    assert second.status_code == 500
    assert second.json == {"ok": False, "error": "smtp offline"}
    assert send_attempts == [receipt_id, receipt_id]

    detail_response = client_with_temp_db.get(f"/receipts/{receipt_id}")
    assert detail_response.status_code == 200
    assert b">failed<" in detail_response.data
    assert b"Retry Send" in detail_response.data

    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT sent_at, last_attempt_at, last_error FROM receipt_queue WHERE id = ?;",
            (receipt_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["sent_at"] is None
    assert row["last_attempt_at"] is not None
    assert row["last_error"] == "smtp offline"


def test_receipt_send_rejects_historical_nonqueued_receipt(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)

    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT snapshot_json FROM receipt_queue WHERE id = ?;",
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
            (json.dumps(snapshot, sort_keys=True), receipt_id),
        )
        conn.commit()
    finally:
        conn.close()

    send_calls: list[int] = []

    def _fake_send(receipt: dict[str, object]) -> list[str]:
        send_calls.append(int(receipt["id"]))
        return ["issue@example.org"]

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    response = client_with_temp_db.post(f"/receipts/{receipt_id}/send?json=1")

    assert response.status_code == 400
    assert response.json == {"ok": False, "error": "Receipt is not queued for email."}
    assert send_calls == []


def test_receipt_send_does_not_resend_after_success(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _insert_holder(
        1,
        name="Issue Holder",
        identifier="IH-1",
        organization="Operations",
        organization_id=9,
        email="issue@example.org",
    )
    _insert_slot(10, "CASE-10", 1)
    _insert_asset(100, "ISSUE-100", location_type="STORAGE", home_slot_id=10, building_room="Storage/A1")
    _occupy_slot(10, 100)
    _login_issue_operator(client_with_temp_db)
    intake_app.SCAN_QUEUE.clear()
    intake_app.SCAN_QUEUE.append(intake_app.Scan.now(asset_tag="ISSUE-100", equipment_type="laptop"))
    commit = client_with_temp_db.post(
        "/issue/commit",
        data={"confirm_reviewed": "on", "confirm_responsibility_ack": "on"},
        follow_redirects=False,
    )
    assert commit.status_code == 302
    receipt_id = _latest_receipt_id()

    send_calls: list[int] = []

    def _fake_send(receipt: dict[str, object]) -> list[str]:
        send_calls.append(int(receipt["id"]))
        return ["issue@example.org"]

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    first = client_with_temp_db.post(f"/receipts/{receipt_id}/send?json=1")
    second = client_with_temp_db.post(f"/receipts/{receipt_id}/send?json=1")

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json == {"ok": False, "error": "Receipt is not queued for email."}
    assert send_calls == [receipt_id]


def test_receipt_send_fails_clearly_when_snapshot_email_is_missing(client_with_temp_db) -> None:
    receipt_id = _create_return_receipt(client_with_temp_db, mixed_holders=True)

    response = client_with_temp_db.post(f"/receipts/{receipt_id}/send?json=1")

    assert response.status_code == 400
    assert response.json == {"ok": False, "error": "Receipt has no stored email recipient."}


def test_admin_can_resend_existing_receipt_without_changing_receipt_or_event_truth(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    admin_id = create_test_user(username="receipt-resend-admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    conn = db.get_connection()
    try:
        row = conn.execute("SELECT snapshot_json FROM receipt_queue WHERE id = ?;", (receipt_id,)).fetchone()
        assert row is not None
        snapshot = json.loads(str(row["snapshot_json"]))
        snapshot["delivery"] = {
            "state": "sent",
            "sent_at": "2026-04-01T12:00:00+00:00",
            "last_attempt_at": "2026-04-01T12:00:00+00:00",
            "last_error": None,
        }
        conn.execute(
            """
            UPDATE receipt_queue
            SET snapshot_json = ?, sent_at = ?, last_attempt_at = ?, last_error = NULL
            WHERE id = ?;
            """,
            (json.dumps(snapshot, sort_keys=True), "2026-04-01T12:00:00+00:00", "2026-04-01T12:00:00+00:00", receipt_id),
        )
        conn.commit()
        receipt_before = conn.execute(
            "SELECT snapshot_json, sent_at, last_attempt_at, last_error FROM receipt_queue WHERE id = ?;",
            (receipt_id,),
        ).fetchone()
        event_count_before = conn.execute("SELECT COUNT(*) AS c FROM asset_events;").fetchone()
    finally:
        conn.close()
    assert receipt_before is not None
    assert event_count_before is not None

    sent_receipts: list[int] = []

    def _fake_send(receipt: dict[str, object]) -> list[str]:
        sent_receipts.append(int(receipt["id"]))
        return ["issue@example.org"]

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    response = client_with_temp_db.post(f"/receipts/{receipt_id}/resend?json=1")

    assert response.status_code == 200
    assert response.json == {
        "ok": True,
        "receipt_id": receipt_id,
        "recipients": ["issue@example.org"],
    }
    assert sent_receipts == [receipt_id]

    conn = db.get_connection()
    try:
        receipt_after = conn.execute(
            "SELECT snapshot_json, sent_at, last_attempt_at, last_error FROM receipt_queue WHERE id = ?;",
            (receipt_id,),
        ).fetchone()
        event_count_after = conn.execute("SELECT COUNT(*) AS c FROM asset_events;").fetchone()
    finally:
        conn.close()

    assert receipt_after is not None
    assert event_count_after is not None
    assert dict(receipt_after) == dict(receipt_before)
    assert int(event_count_after["c"]) == int(event_count_before["c"])


def test_operator_cannot_trigger_receipt_resend(client_with_temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    send_calls: list[int] = []

    def _fake_send(receipt: dict[str, object]) -> list[str]:
        send_calls.append(int(receipt["id"]))
        return ["issue@example.org"]

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    response = client_with_temp_db.post(
        f"/receipts/{receipt_id}/resend",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 403
    assert response.json == {"ok": False, "error": "Forbidden"}
    assert send_calls == []


def test_admin_get_receipt_resend_redirects_with_plain_message_without_sending(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    admin_id = create_test_user(username="receipt-resend-get-admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)
    send_calls: list[int] = []

    def _fake_send(receipt: dict[str, object]) -> list[str]:
        send_calls.append(int(receipt["id"]))
        return ["issue@example.org"]

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}/resend", follow_redirects=True)

    assert response.status_code == 200
    assert b"Use the receipt detail page button to resend receipt email." in response.data
    assert send_calls == []


def test_operator_get_receipt_resend_remains_forbidden(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    send_calls: list[int] = []

    def _fake_send(receipt: dict[str, object]) -> list[str]:
        send_calls.append(int(receipt["id"]))
        return ["issue@example.org"]

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    response = client_with_temp_db.get(
        f"/receipts/{receipt_id}/resend",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 403
    assert response.json == {"ok": False, "error": "Forbidden"}
    assert send_calls == []


def test_receipt_resend_uses_configured_cc_and_existing_email_content(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    admin_id = create_test_user(username="receipt-resend-cc-admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT snapshot_json FROM receipt_queue WHERE id = ?;", (receipt_id,)).fetchone()
        assert row is not None
        snapshot = json.loads(str(row["snapshot_json"]))
        snapshot["delivery"] = {
            "state": "sent",
            "sent_at": "2026-04-01T12:00:00+00:00",
            "last_attempt_at": "2026-04-01T12:00:00+00:00",
            "last_error": None,
        }
        conn.execute(
            """
            UPDATE receipt_queue
            SET snapshot_json = ?, sent_at = ?, last_attempt_at = ?, last_error = NULL
            WHERE id = ?;
            """,
            (json.dumps(snapshot, sort_keys=True), "2026-04-01T12:00:00+00:00", "2026-04-01T12:00:00+00:00", receipt_id),
        )
        conn.commit()
    finally:
        conn.close()
    captured: dict[str, object] = {}

    def _fake_send(message: EmailMessage) -> None:
        captured["message"] = message

    monkeypatch.setenv("ASSETTRACK_SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("ASSETTRACK_RECEIPT_CC_EMAIL", "oversight@example.org")
    monkeypatch.setattr(intake_app, "_send_email_message", _fake_send)

    response = client_with_temp_db.post(f"/receipts/{receipt_id}/resend?json=1")

    assert response.status_code == 200
    message = captured["message"]
    assert isinstance(message, EmailMessage)
    assert message["To"] == "issue@example.org"
    assert message["Cc"] == "oversight@example.org"
    assert "Receipt key:" in message.get_body(preferencelist=("plain",)).get_content()
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    pdf_text = _extract_pdf_text(attachments[0].get_payload(decode=True))
    assert "ISSUE-100" in pdf_text
    assert "Audit Details" not in pdf_text


def test_receipt_resend_failure_is_plain_and_does_not_change_receipt_truth(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    admin_id = create_test_user(username="receipt-resend-fail-admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)

    conn = db.get_connection()
    try:
        row = conn.execute("SELECT snapshot_json FROM receipt_queue WHERE id = ?;", (receipt_id,)).fetchone()
        assert row is not None
        snapshot = json.loads(str(row["snapshot_json"]))
        snapshot["delivery"] = {
            "state": "sent",
            "sent_at": "2026-04-01T12:00:00+00:00",
            "last_attempt_at": "2026-04-01T12:00:00+00:00",
            "last_error": None,
        }
        conn.execute(
            """
            UPDATE receipt_queue
            SET snapshot_json = ?, sent_at = ?, last_attempt_at = ?, last_error = NULL
            WHERE id = ?;
            """,
            (json.dumps(snapshot, sort_keys=True), "2026-04-01T12:00:00+00:00", "2026-04-01T12:00:00+00:00", receipt_id),
        )
        conn.commit()
        snapshot_before = conn.execute(
            "SELECT snapshot_json FROM receipt_queue WHERE id = ?;",
            (receipt_id,),
        ).fetchone()
    finally:
        conn.close()
    assert snapshot_before is not None

    def _fake_send(_receipt: dict[str, object]) -> list[str]:
        raise RuntimeError("smtp.internal.example refused credentials")

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    response = client_with_temp_db.post(f"/receipts/{receipt_id}/resend?json=1")

    assert response.status_code == 500
    assert response.json == {"ok": False, "error": "Receipt email could not be resent."}

    conn = db.get_connection()
    try:
        snapshot_after = conn.execute(
            "SELECT snapshot_json FROM receipt_queue WHERE id = ?;",
            (receipt_id,),
        ).fetchone()
    finally:
        conn.close()
    assert snapshot_after is not None
    assert snapshot_after["snapshot_json"] == snapshot_before["snapshot_json"]


def test_admin_resend_does_not_bypass_queued_send_path(
    client_with_temp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    admin_id = create_test_user(username="receipt-resend-queued-admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)
    send_calls: list[int] = []

    def _fake_send(receipt: dict[str, object]) -> list[str]:
        send_calls.append(int(receipt["id"]))
        return ["issue@example.org"]

    monkeypatch.setattr(intake_app, "_send_receipt_email", _fake_send)

    response = client_with_temp_db.post(f"/receipts/{receipt_id}/resend?json=1")

    assert response.status_code == 500
    assert response.json == {"ok": False, "error": "Receipt email could not be resent."}
    assert send_calls == []


def test_receipt_detail_shows_resend_action_only_to_admin_after_send(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT snapshot_json FROM receipt_queue WHERE id = ?;", (receipt_id,)).fetchone()
        assert row is not None
        snapshot = json.loads(str(row["snapshot_json"]))
        snapshot["delivery"] = {
            "state": "sent",
            "sent_at": "2026-04-01T12:00:00+00:00",
            "last_attempt_at": "2026-04-01T12:00:00+00:00",
            "last_error": None,
        }
        conn.execute(
            """
            UPDATE receipt_queue
            SET snapshot_json = ?, sent_at = ?, last_attempt_at = ?, last_error = NULL
            WHERE id = ?;
            """,
            (json.dumps(snapshot, sort_keys=True), "2026-04-01T12:00:00+00:00", "2026-04-01T12:00:00+00:00", receipt_id),
        )
        conn.commit()
    finally:
        conn.close()

    operator_response = client_with_temp_db.get(f"/receipts/{receipt_id}")
    assert operator_response.status_code == 200
    assert b"Resend receipt email" not in operator_response.data

    admin_id = create_test_user(username="receipt-resend-view-admin", password="admin-pass", role="admin")
    login_session(client_with_temp_db, admin_id)
    admin_response = client_with_temp_db.get(f"/receipts/{receipt_id}")
    assert admin_response.status_code == 200
    assert f'action="/receipts/{receipt_id}/resend"'.encode("utf-8") in admin_response.data
    assert b"Resend receipt email" in admin_response.data


def test_send_receipt_email_adds_configured_cc_recipient(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    receipt = {
        "id": 7,
        "receipt_key": "R-7",
        "display_title": "Issue Receipt",
        "receipt_type": "ISSUE",
        "commit_at": "2026-01-01T00:00:00Z",
        "holder_display_name": "Issue Holder",
        "holder_snapshot": {"name": "Issue Holder"},
        "organization_snapshot": {"organization": "Operations"},
        "location_context": {"building_room": "HQ North/210"},
        "recipient_email": "issue@example.org",
        "delivery": {"state": "pending", "last_error": "SMTP timeout"},
        "assets": [
            {
                "asset_tag": "ISSUE-100",
                "equipment_type": "Laptop",
                "serial_number": "SN-ISSUE-100",
                "manufacturer": "Dell",
                "model": "Latitude",
                "model_code": "LAT-14",
                "from_location_type": "IN_CUSTODY",
                "to_location_type": "IN_CUSTODY",
            }
        ],
    }

    captured: dict[str, object] = {}

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout

        def __enter__(self) -> "_FakeSMTP":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def send_message(self, message: EmailMessage) -> None:
            captured["message"] = message

    monkeypatch.setenv("ASSETTRACK_SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("ASSETTRACK_RECEIPT_FROM_EMAIL", "assettrack@example.org")
    monkeypatch.setenv("ASSETTRACK_RECEIPT_CC_EMAIL", "  Oversight@example.org  ")
    monkeypatch.setattr(intake_app.smtplib, "SMTP", _FakeSMTP)

    recipients = intake_app._send_receipt_email(receipt)

    assert recipients == ["issue@example.org"]
    message = captured["message"]
    assert isinstance(message, EmailMessage)
    assert message["To"] == "issue@example.org"
    assert message["Cc"] == "oversight@example.org"
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    pdf_text = _extract_pdf_text(attachments[0].get_payload(decode=True))
    assert "Issue Receipt" in pdf_text
    assert "Receipt attached for your records." in pdf_text
    assert "ISSUE-100" in pdf_text
    assert "Audit Details" not in pdf_text
    assert "Receipt ID" not in pdf_text
    assert "Receipt key" not in pdf_text
    assert "Recipient email" not in pdf_text
    assert "Delivery issue" not in pdf_text
    assert "Receipt delivery queued. Custody is already recorded." not in pdf_text


def test_receipt_cc_recipients_use_local_setting_before_env_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    try:
        with conn:
            write_receipt_cc_setting(conn, "Local@example.org")
    finally:
        conn.close()

    monkeypatch.setenv("ASSETTRACK_RECEIPT_CC_EMAIL", "env@example.org")

    assert intake_app._receipt_cc_recipients() == ["local@example.org"]


def test_send_receipt_email_omits_cc_when_config_is_blank(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    receipt = {
        "id": 8,
        "receipt_key": "R-8",
        "display_title": "Issue Receipt",
        "receipt_type": "ISSUE",
        "commit_at": "2026-01-01T00:00:00Z",
        "holder_display_name": "Issue Holder",
        "holder_snapshot": {"name": "Issue Holder"},
        "recipient_email": "issue@example.org",
        "assets": [{"asset_tag": "ISSUE-101"}],
    }

    captured: dict[str, object] = {}

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout

        def __enter__(self) -> "_FakeSMTP":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def send_message(self, message: EmailMessage) -> None:
            captured["message"] = message

    monkeypatch.setenv("ASSETTRACK_SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("ASSETTRACK_RECEIPT_FROM_EMAIL", "assettrack@example.org")
    monkeypatch.setenv("ASSETTRACK_RECEIPT_CC_EMAIL", "   ")
    monkeypatch.setattr(intake_app.smtplib, "SMTP", _FakeSMTP)

    recipients = intake_app._send_receipt_email(receipt)

    assert recipients == ["issue@example.org"]
    message = captured["message"]
    assert isinstance(message, EmailMessage)
    assert message["To"] == "issue@example.org"
    assert message["Cc"] is None


def test_receipt_pdf_is_deterministic_for_same_snapshot(client_with_temp_db) -> None:
    receipt_id = _create_issue_receipt(client_with_temp_db)

    first = client_with_temp_db.get(f"/receipts/{receipt_id}/pdf")
    second = client_with_temp_db.get(f"/receipts/{receipt_id}/pdf")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.data == second.data


def test_receipt_pdf_uses_snapshot_truth_not_live_tables(client_with_temp_db) -> None:
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
            SET manufacturer = ?, model = ?, model_code = ?
            WHERE id = 100;
            """,
            ("Changed Maker", "Changed Model", "NEW-CODE"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.get(f"/receipts/{receipt_id}/pdf")

    assert response.status_code == 200
    pdf_text = _extract_pdf_text(response.data)
    assert "Issue Holder" in pdf_text
    assert "Dell / Latitude (LAT-14)" in pdf_text
    assert "Mutated Holder" not in pdf_text
    assert "Changed Maker" not in pdf_text


def test_return_receipt_pdf_lists_multiple_holders_when_batch_is_mixed(client_with_temp_db) -> None:
    receipt_id = _create_return_receipt(client_with_temp_db, mixed_holders=True)

    response = client_with_temp_db.get(f"/receipts/{receipt_id}/pdf")

    assert response.status_code == 200
    pdf_text = _extract_pdf_text(response.data)
    assert "Return Receipt" in pdf_text
    assert "2 assets returned from Return Holder One, Return Holder Two" in pdf_text
    assert "Location" in pdf_text
    assert "HQ North/210, HQ North/211" in pdf_text
    assert "RETURN-200" in pdf_text
    assert "RETURN-201" in pdf_text
