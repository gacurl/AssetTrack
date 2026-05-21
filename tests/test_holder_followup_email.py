from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")

    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO holders (id, holder_type, name, organization, identifier, email, contact_info, created_at, updated_at)
        VALUES (1, 'PERSON', 'Followup Holder', 'Ops', 'FH-1', 'holder.followup@example.org', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    intake_app.app.testing = True
    return intake_app.app.test_client()


def _counts() -> tuple[int, int]:
    conn = db.get_connection()
    try:
        events = conn.execute("SELECT COUNT(*) AS c FROM asset_events;").fetchone()
        receipts = conn.execute("SELECT COUNT(*) AS c FROM receipt_queue;").fetchone()
    finally:
        conn.close()
    return int(events["c"]), int(receipts["c"])


def test_holder_detail_shows_manual_followup_action_and_language(client_with_temp_db) -> None:
    operator_id = create_test_user(username="operator-followup-ui", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)

    response = client_with_temp_db.get("/holders/1")

    assert response.status_code == 200
    assert b"Send this Holder a Follow-Up Email" in response.data
    assert b"Follow-up emails are manual reminders. They do not record or change custody." in response.data
    assert b'action="/holders/1/follow-up-email"' in response.data
    assert b"Send Follow-Up Email" in response.data
    assert b"Send Receipt Email" not in response.data


@pytest.mark.parametrize("role", ["operator", "admin"])
def test_followup_send_allowed_for_operator_and_admin_and_does_not_mutate_custody_or_receipts(
    client_with_temp_db,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    user_id = create_test_user(username=f"{role}-followup-send", password="pass", role=role)
    login_session(client_with_temp_db, user_id)

    sent_messages: list[EmailMessage] = []

    def _fake_send(message: EmailMessage) -> None:
        sent_messages.append(message)

    monkeypatch.setenv("ASSETTRACK_SMTP_HOST", "smtp.example.org")
    monkeypatch.setattr(intake_app, "_send_email_message", _fake_send)

    before_events, before_receipts = _counts()

    response = client_with_temp_db.post(
        "/holders/1/follow-up-email",
        data={"followup_note": "Please confirm return timeline.", "return_to": "/holders"},
        follow_redirects=True,
    )

    after_events, after_receipts = _counts()

    assert response.status_code == 200
    assert b"Holder follow-up email sent to holder.followup@example.org." in response.data
    assert b"receipt sent" not in response.data.lower()
    assert before_events == after_events
    assert before_receipts == after_receipts
    assert len(sent_messages) == 1
    message = sent_messages[0]
    assert "Holder Follow-Up" in str(message["Subject"] or "")
    assert str(message["To"] or "") == "holder.followup@example.org"
    body = message.get_content()
    assert "manual follow-up reminder" in body
    assert "does not record, prove, or change custody" in body
    assert "Please confirm return timeline." in body


def test_followup_send_requires_login(client_with_temp_db) -> None:
    response = client_with_temp_db.post(
        "/holders/1/follow-up-email",
        data={"followup_note": "test"},
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_followup_send_fails_safely_when_email_not_configured_and_does_not_mutate_custody_or_receipts(
    client_with_temp_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_id = create_test_user(username="operator-followup-fail", password="op-pass", role="operator")
    login_session(client_with_temp_db, operator_id)
    monkeypatch.delenv("ASSETTRACK_SMTP_HOST", raising=False)

    before_events, before_receipts = _counts()

    response = client_with_temp_db.post(
        "/holders/1/follow-up-email",
        data={"followup_note": "Need acknowledgment.", "return_to": "/holders"},
        follow_redirects=True,
    )

    after_events, after_receipts = _counts()

    assert response.status_code == 200
    assert b"Follow-up email delivery is not configured." in response.data
    assert before_events == after_events
    assert before_receipts == after_receipts
