from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

import assettrack.db as db
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def client_with_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.close()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def _login_operator(client) -> None:
    operator_id = create_test_user(username="custody-report-operator", password="op-pass", role="operator")
    login_session(client, operator_id)


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0])
        for table in ("assets", "asset_events", "holders", "slots")
    }


def _snapshot(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    return {
        "assets": [dict(row) for row in conn.execute("SELECT * FROM assets ORDER BY id;").fetchall()],
        "asset_events": [dict(row) for row in conn.execute("SELECT * FROM asset_events ORDER BY id;").fetchall()],
        "holders": [dict(row) for row in conn.execute("SELECT * FROM holders ORDER BY id;").fetchall()],
        "slots": [dict(row) for row in conn.execute("SELECT * FROM slots ORDER BY id;").fetchall()],
    }


def _insert_holder(conn: sqlite3.Connection, holder_id: int, name: str, organization: str) -> None:
    conn.execute(
        """
        INSERT INTO holders (
            id, holder_type, name, organization, identifier, email, contact_info, created_at, updated_at
        )
        VALUES (?, 'PERSON', ?, ?, ?, '', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """,
        (holder_id, name, organization, f"H-{holder_id}"),
    )


def _insert_slot(conn: sqlite3.Connection, slot_id: int, case_name: str, slot_position: int) -> None:
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (?, ?, ?, NULL);
        """,
        (slot_id, case_name, slot_position),
    )


def _insert_asset(
    conn: sqlite3.Connection,
    asset_tag: str,
    *,
    serial_number: str = "SER",
    equipment_type: str = "laptop",
    location_type: str = "STORAGE",
    current_holder_id: int | None = None,
    home_slot_id: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO assets (
            asset_tag, serial_number, equipment_type, location_type, current_holder_id, home_slot_id
        )
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        (asset_tag, serial_number, equipment_type, location_type, current_holder_id, home_slot_id),
    )


def _insert_event(
    conn: sqlite3.Connection,
    asset_tag: str,
    event_type: str,
    event_date: str,
    *,
    holder_id: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
        VALUES (?, ?, ?, 'test', NULL, '{}', ?);
        """,
        (asset_tag, event_type, event_date, holder_id),
    )


def _seed_custody_fixture() -> None:
    conn = db.get_connection()
    try:
        _insert_holder(conn, 1, "Alice Holder", "Mission A")
        _insert_holder(conn, 2, "Bob Holder", "Mission B")
        _insert_slot(conn, 10, "CASE-1", 4)
        _insert_slot(conn, 11, "CASE-2", 7)
        _insert_asset(conn, "RETURNED-1", serial_number="SER-R", equipment_type="laptop", home_slot_id=10)
        _insert_asset(
            conn,
            "OUT-1",
            serial_number="SER-O",
            equipment_type="router",
            location_type="IN_CUSTODY",
            current_holder_id=2,
            home_slot_id=11,
        )
        _insert_asset(conn, "BAD-1", serial_number="SER-B")
        _insert_event(conn, "RETURNED-1", "ISSUE", "2026-01-01T00:00:00Z", holder_id=1)
        _insert_event(conn, "RETURNED-1", "RETURN", "2026-01-03T06:00:00Z")
        _insert_event(conn, "OUT-1", "ISSUE", "2026-01-05T00:00:00Z", holder_id=2)
        _insert_event(conn, "BAD-1", "RETURN", "2026-01-06T00:00:00Z")
        conn.commit()
    finally:
        conn.close()


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_preview_route_renders_model_sections_and_known_interval(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)
    _seed_custody_fixture()

    response = client_with_temp_db.get("/report/custody-accountability")

    assert response.status_code == 200
    assert b"Asset Custody / Accountability" in response.data
    assert b"OUTSTANDING ASSETS REQUIRE ATTENTION" in response.data
    assert b"Total active assets" in response.data
    assert b"RETURNED-1" in response.data
    assert b"2026-01-01 00:00 UTC" in response.data
    assert b"2026-01-03 06:00 UTC" in response.data
    assert b"2d 6h" in response.data


def test_preview_is_read_only_and_shows_holder_outstanding_and_exception(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)
    _seed_custody_fixture()
    conn = db.get_connection()
    before_counts = _counts(conn)
    before_snapshot = _snapshot(conn)
    conn.close()

    response = client_with_temp_db.get("/report/custody-accountability")

    conn = db.get_connection()
    after_counts = _counts(conn)
    after_snapshot = _snapshot(conn)
    conn.close()
    assert response.status_code == 200
    assert b"Bob Holder (Mission B)" in response.data
    assert b"OUT-1" in response.data
    assert b"OUTSTANDING" in response.data
    assert b"BAD-1" in response.data
    assert b"no preceding open ISSUE" in response.data
    assert before_counts == after_counts
    assert before_snapshot == after_snapshot


def test_reports_page_links_to_custody_accountability_preview(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)

    response = client_with_temp_db.get("/report")

    assert response.status_code == 200
    assert b'href="/report/custody-accountability"' in response.data
    assert b"Asset Custody / Accountability" in response.data


def test_pdf_response_and_representative_content(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)
    _seed_custody_fixture()

    response = client_with_temp_db.get("/report/custody-accountability/pdf")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF-")
    disposition = response.headers.get("Content-Disposition") or ""
    assert "attachment;" in disposition
    assert "assettrack-custody-accountability-" in disposition
    pdf_text = _pdf_text(response.data)
    assert "Asset Custody / Accountability" in pdf_text
    assert "RETURNED-1" in pdf_text
    assert "OUT-1" in pdf_text
    assert "Bob Holder" in pdf_text
    assert "OUTSTANDING" in pdf_text
    assert "BAD-1" in pdf_text


def test_pdf_generation_is_read_only(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)
    _seed_custody_fixture()
    conn = db.get_connection()
    before_counts = _counts(conn)
    before_snapshot = _snapshot(conn)
    conn.close()

    response = client_with_temp_db.get("/report/custody-accountability/pdf")

    conn = db.get_connection()
    after_counts = _counts(conn)
    after_snapshot = _snapshot(conn)
    conn.close()
    assert response.status_code == 200
    assert before_counts == after_counts
    assert before_snapshot == after_snapshot


def test_multi_page_pdf_generation(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)
    conn = db.get_connection()
    try:
        _insert_holder(conn, 3, "Large Holder", "Mission Large")
        for index in range(60):
            asset_tag = f"MP-{index:03d}"
            _insert_asset(conn, asset_tag, serial_number=f"SER-{index:03d}", location_type="IN_CUSTODY", current_holder_id=3)
            _insert_event(conn, asset_tag, "ISSUE", "2026-01-01T00:00:00Z", holder_id=3)
        conn.commit()
    finally:
        conn.close()

    response = client_with_temp_db.get("/report/custody-accountability/pdf")
    reader = PdfReader(BytesIO(response.data))

    assert response.status_code == 200
    assert len(reader.pages) > 1
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "MP-000" in pdf_text
    assert "MP-059" in pdf_text
