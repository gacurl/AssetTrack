# file: tests/test_dashboard_drilldowns.py
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

import assettrack.db as db
from assettrack.drilldowns import (
    get_holder_custody_detail,
    list_case_summaries,
    list_holders_in_custody,
)
from assettrack.event_types import issue_event_type_values
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


@pytest.fixture
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "assettrack.db")
    conn = db.get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_tag TEXT NOT NULL UNIQUE,
            equipment_type TEXT NULL,
            manufacturer TEXT NULL,
            model TEXT NULL,
            location_type TEXT NULL,
            current_holder_id INTEGER NULL,
            home_slot_id INTEGER NULL
        );
        """
    )
    conn.commit()
    intake_app.app.testing = True
    client = intake_app.app.test_client()
    operator_user_id = create_test_user(username="operator", password="op-pass", role="operator")
    login_session(client, operator_user_id)
    intake_app.SCAN_QUEUE.clear()
    yield conn, client
    intake_app.SCAN_QUEUE.clear()
    conn.close()


def _insert_holder(conn, holder_id: int, name: str, *, organization: str | None = None) -> None:
    now = "2026-01-01T00:00:00Z"
    conn.execute(
        """
        INSERT INTO holders (id, holder_type, name, organization, identifier, contact_info, created_at, updated_at)
        VALUES (?, 'PERSON', ?, ?, NULL, NULL, ?, ?);
        """,
        (holder_id, name, organization, now, now),
    )


def _insert_asset(
    conn,
    asset_tag: str,
    *,
    location_type: str,
    holder_id: int | None = None,
    equipment_type: str | None = None,
    manufacturer: str | None = None,
    model: str | None = None,
    home_slot_id: int | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO assets (
            asset_tag,
            equipment_type,
            manufacturer,
            model,
            location_type,
            current_holder_id,
            home_slot_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (asset_tag, equipment_type, manufacturer, model, location_type, holder_id, home_slot_id),
    )
    return int(cursor.lastrowid)


def _insert_issue_event(conn, asset_tag: str, event_date: str, *, legacy: bool = False) -> None:
    issue_values = issue_event_type_values()
    event_type = issue_values[1] if legacy else issue_values[0]
    conn.execute(
        """
        INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
        VALUES (?, ?, ?, 'tester', NULL, NULL, NULL);
        """,
        (asset_tag, event_type, event_date),
    )


def _insert_slot(conn, slot_id: int, case_name: str, slot_position: int) -> None:
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (?, ?, ?, NULL);
        """,
        (slot_id, case_name, slot_position),
    )


def _occupy_slot(conn, slot_id: int, asset_id: int) -> None:
    conn.execute(
        """
        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
        VALUES (?, ?, '2026-01-01T00:00:00Z');
        """,
        (slot_id, asset_id),
    )


def _count_rows(conn, table_name: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) AS c FROM {table_name};").fetchone()["c"])


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_dashboard_holders_route_returns_200_and_is_read_only(app_client) -> None:
    conn, client = app_client
    _insert_holder(conn, 1, "Alpha")
    _insert_asset(conn, "AT-1", location_type="IN_CUSTODY", holder_id=1)
    conn.commit()

    counts_before = (
        conn.execute("SELECT COUNT(*) AS c FROM assets;").fetchone()["c"],
        conn.execute("SELECT COUNT(*) AS c FROM asset_events;").fetchone()["c"],
        conn.execute("SELECT COUNT(*) AS c FROM slot_occupancy;").fetchone()["c"],
    )

    response = client.get("/dashboard/holders")
    assert response.status_code == 200
    assert b"Holders With Assets Out" in response.data
    assert b"Back to Dashboard" not in response.data
    assert b"Back to Report" not in response.data

    counts_after = (
        conn.execute("SELECT COUNT(*) AS c FROM assets;").fetchone()["c"],
        conn.execute("SELECT COUNT(*) AS c FROM asset_events;").fetchone()["c"],
        conn.execute("SELECT COUNT(*) AS c FROM slot_occupancy;").fetchone()["c"],
    )
    assert counts_before == counts_after


def test_dashboard_holder_detail_404_when_holder_missing(app_client) -> None:
    _, client = app_client
    response = client.get("/dashboard/holders/999")
    assert response.status_code == 404


def test_dashboard_holder_detail_200_none_when_no_assets(app_client) -> None:
    conn, client = app_client
    _insert_holder(conn, 1, "No Custody")
    conn.commit()

    response = client.get("/dashboard/holders/1")
    assert response.status_code == 200
    assert b"No assets are currently out for this holder." in response.data


def test_dashboard_cases_route_200_and_missing_case_404(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 10, "CASE-A", 1)
    _insert_slot(conn, 11, "CASE-A", 2)
    conn.commit()

    cases_response = client.get("/dashboard/cases")
    assert cases_response.status_code == 200
    assert b"Case Summary" in cases_response.data
    assert b"Status" in cases_response.data
    assert b"LOW - Getting tight" in cases_response.data
    assert b"status-dot low" in cases_response.data

    missing_response = client.get("/dashboard/cases/CASE-MISSING")
    assert missing_response.status_code == 404


def test_dashboard_cases_renders_case_filter_input(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 15, "CASE-FILTER", 1)
    conn.commit()

    response = client.get("/dashboard/cases")
    assert response.status_code == 200
    assert b'name="q"' in response.data
    assert b"Find case" not in response.data


def test_dashboard_cases_case_name_filter_shows_only_matches_and_keeps_read_only(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 21, "CASE-111", 1)
    _insert_slot(conn, 22, "CASE-999", 1)
    conn.commit()

    response = client.get("/dashboard/cases?q=111")
    assert response.status_code == 200
    assert b'href="/dashboard/cases/CASE-111"' in response.data
    assert b'CASE-999' not in response.data
    assert _count_rows(conn, "asset_events") == 0
    assert _count_rows(conn, "receipt_queue") == 0


def test_dashboard_cases_case_name_filter_no_match_message(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 23, "CASE-ABC", 1)
    conn.commit()

    response = client.get("/dashboard/cases?q=ZZZ")
    assert response.status_code == 200
    assert b"No cases match that search." in response.data


def test_dashboard_case_detail_200_includes_expected_slot_positions(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 10, "CASE-A", 1)
    _insert_slot(conn, 11, "CASE-A", 2)
    _insert_slot(conn, 12, "CASE-A", 3)
    asset_id = _insert_asset(conn, "AT-SLOTTED", location_type="STORAGE")
    _insert_asset(conn, "AT-OUT", location_type="IN_CUSTODY", holder_id=1, home_slot_id=12)
    conn.execute(
        """
        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
        VALUES (10, ?, '2026-01-01T00:00:00Z');
        """,
        (asset_id,),
    )
    conn.commit()

    response = client.get("/dashboard/cases/CASE-A")
    assert response.status_code == 200
    assert b"Case Status" in response.data
    assert b"LOW - Getting tight" in response.data
    assert b"status-dot low" in response.data
    assert b"Total slots:</strong> 3" in response.data
    assert b"Occupied slots:</strong> 1" in response.data
    assert b"Empty slots:</strong> 2" in response.data
    assert b"Check boxes to select assets." in response.data
    assert b"Select all" in response.data
    assert b"Select all eligible assets" not in response.data
    assert b'data-select-all-eligible="issue"' in response.data
    assert b'data-select-all-eligible="return"' in response.data
    assert b'data-eligible-asset="issue"' in response.data
    assert b'data-eligible-asset="return"' in response.data
    assert b'case-return-selection-form' in response.data
    assert b"Assets Issued Out" in response.data
    assert b"Assets Out From This Case" not in response.data
    assert b"Slot Position" in response.data
    assert b">1<" in response.data
    assert b">2<" in response.data
    assert b"AT-SLOTTED" in response.data
    assert b"AT-OUT" in response.data
    assert b"Empty" in response.data


def test_dashboard_case_detail_asset_tags_link_to_asset_history(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 20, "CASE-LINK", 1)
    asset_id = _insert_asset(conn, "AT-LINK-1", location_type="STORAGE")
    _occupy_slot(conn, 20, asset_id)
    conn.commit()

    response = client.get("/dashboard/cases/CASE-LINK")

    assert response.status_code == 200
    assert b'href="/assets/history?asset_tag=AT-LINK-1' in response.data
    assert b">AT-LINK-1</a>" in response.data


def test_dashboard_case_detail_shows_stored_asset_wording(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 21, "CASE-12", 4)
    asset_id = _insert_asset(conn, "AT-STORED-1", location_type="STORAGE")
    _occupy_slot(conn, 21, asset_id)
    conn.commit()

    response = client.get("/dashboard/cases/CASE-12")

    assert response.status_code == 200
    assert b"Stored in CASE-12, Slot 4" in response.data


def test_dashboard_case_detail_shows_issued_asset_holder(app_client) -> None:
    conn, client = app_client
    _insert_holder(conn, 22, "Jamie Holder", organization="Field Ops")
    _insert_slot(conn, 22, "CASE-ISSUED", 4)
    _insert_asset(conn, "AT-ISSUED-1", location_type="IN_CUSTODY", holder_id=22, home_slot_id=22)
    conn.commit()

    response = client.get("/dashboard/cases/CASE-ISSUED")

    assert response.status_code == 200
    assert b"Issued to Jamie Holder (Field Ops)" in response.data


def test_dashboard_case_detail_issued_asset_with_home_slot_is_not_stored(app_client) -> None:
    conn, client = app_client
    _insert_holder(conn, 23, "Case Holder", organization="Ops")
    _insert_slot(conn, 23, "CASE-12", 4)
    _insert_asset(conn, "AT-OUT-HOME", location_type="IN_CUSTODY", holder_id=23, home_slot_id=23)
    conn.commit()

    response = client.get("/dashboard/cases/CASE-12")

    assert response.status_code == 200
    assert b"AT-OUT-HOME" in response.data
    assert b"Issued to Case Holder (Ops)" in response.data
    assert b"Home slot: CASE-12, Slot 4" in response.data
    assert b"Stored in CASE-12, Slot 4" not in response.data


def test_case_inventory_preview_supports_mixed_case_and_is_read_only(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 101, "CASE-PRINT", 1)
    _insert_slot(conn, 102, "CASE-PRINT", 2)
    _insert_slot(conn, 103, "CASE-PRINT", 3)
    laptop_id = _insert_asset(
        conn,
        "LAP-100",
        location_type="STORAGE",
        equipment_type="laptop",
        manufacturer="Dell",
        model="Latitude",
    )
    switch_id = _insert_asset(
        conn,
        "SW-100",
        location_type="STORAGE",
        equipment_type="switch",
        manufacturer="Cisco",
        model="Catalyst",
    )
    router_id = _insert_asset(
        conn,
        "RTR-100",
        location_type="STORAGE",
        equipment_type="router",
        manufacturer="Juniper",
        model="MX",
    )
    _occupy_slot(conn, 101, laptop_id)
    _occupy_slot(conn, 102, switch_id)
    _occupy_slot(conn, 103, router_id)
    conn.commit()

    counts_before = (
        _count_rows(conn, "assets"),
        _count_rows(conn, "asset_events"),
        _count_rows(conn, "slot_occupancy"),
    )

    response = client.get("/report/case-inventory/preview?case_select=CASE-PRINT")

    counts_after = (
        _count_rows(conn, "assets"),
        _count_rows(conn, "asset_events"),
        _count_rows(conn, "slot_occupancy"),
    )
    assert response.status_code == 200
    assert b"Case Inventory" in response.data
    assert b"Case number:</strong><br />CASE-PRINT" in response.data
    assert b"Asset count:</strong><br />3" in response.data
    assert b"LAP-100" in response.data
    assert b"SW-100" in response.data
    assert b"RTR-100" in response.data
    assert b"Laptop" in response.data
    assert b"Switch" in response.data
    assert b"Router" in response.data
    assert b"Dell / Latitude" in response.data
    assert b"Cisco / Catalyst" in response.data
    assert b"Juniper / MX" in response.data
    assert b"Slot 1" in response.data
    assert b"Download PDF" in response.data
    assert counts_before == counts_after


def test_case_inventory_entry_supports_empty_and_invalid_cases(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 110, "CASE-EMPTY", 1)
    conn.commit()

    entry_response = client.get("/report/case-inventory")
    assert entry_response.status_code == 200
    assert b"Preview Inventory" in entry_response.data
    assert b"CASE-EMPTY" in entry_response.data

    empty_response = client.get("/report/case-inventory/preview?case_name=case-empty")
    assert empty_response.status_code == 200
    assert b"Case number:</strong><br />CASE-EMPTY" in empty_response.data
    assert b"Asset count:</strong><br />0" in empty_response.data
    assert b"No assets currently in this case." in empty_response.data

    invalid_response = client.get("/report/case-inventory/preview?case_name=CASE-MISSING")
    assert invalid_response.status_code == 404
    assert b"Case Not Found" in invalid_response.data
    assert b"CASE-MISSING" in invalid_response.data


def test_case_inventory_routes_require_login(app_client) -> None:
    _, client = app_client
    with client.session_transaction() as sess:
        sess.clear()

    for path in [
        "/report/case-inventory",
        "/report/case-inventory/preview?case_name=CASE-1",
        "/report/case-inventory/pdf?case_name=CASE-1",
    ]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 403


def test_case_inventory_pdf_uses_existing_data_and_is_read_only(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 120, "CASE-PDF", 1)
    asset_id = _insert_asset(
        conn,
        "PDF-100",
        location_type="STORAGE",
        equipment_type="laptop",
        manufacturer="HP",
        model="EliteBook",
    )
    _occupy_slot(conn, 120, asset_id)
    conn.commit()

    counts_before = (
        _count_rows(conn, "assets"),
        _count_rows(conn, "asset_events"),
        _count_rows(conn, "slot_occupancy"),
    )

    response = client.get("/report/case-inventory/pdf?case_name=CASE-PDF")

    counts_after = (
        _count_rows(conn, "assets"),
        _count_rows(conn, "asset_events"),
        _count_rows(conn, "slot_occupancy"),
    )
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF-")
    assert "assettrack-case-inventory-CASE-PDF-" in (response.headers.get("Content-Disposition") or "")
    pdf_text = _extract_pdf_text(response.data)
    assert "Case Inventory" in pdf_text
    assert "Case number: CASE-PDF" in pdf_text
    assert "Asset count: 1" in pdf_text
    assert "PDF-100" in pdf_text
    assert "Laptop" in pdf_text
    assert "HP / EliteBook" in pdf_text
    assert "Slot 1" in pdf_text
    assert counts_before == counts_after


def test_case_inventory_pdf_supports_multi_page_case(app_client) -> None:
    conn, client = app_client
    for index in range(1, 90):
        slot_id = 200 + index
        _insert_slot(conn, slot_id, "CASE-LONG", index)
        asset_id = _insert_asset(
            conn,
            f"LONG-{index:03d}",
            location_type="STORAGE",
            equipment_type="laptop",
            manufacturer="Lenovo",
            model=f"T{index:03d}",
        )
        _occupy_slot(conn, slot_id, asset_id)
    conn.commit()

    response = client.get("/report/case-inventory/pdf?case_name=CASE-LONG")

    assert response.status_code == 200
    reader = PdfReader(BytesIO(response.data))
    assert len(reader.pages) > 1
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "LONG-001" in pdf_text
    assert "LONG-089" in pdf_text
    assert "Asset count: 89" in pdf_text


def test_case_detail_start_issue_populates_queue_without_events_or_receipts(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 20, "CASE-I", 1)
    asset_id = _insert_asset(conn, "ISSUE-READY", location_type="STORAGE", home_slot_id=20)
    _occupy_slot(conn, 20, asset_id)
    conn.commit()

    response = client.post(
        "/dashboard/cases/CASE-I/queue",
        data={"workflow_action": "issue", "asset_tag": "ISSUE-READY"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/issue")
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["ISSUE-READY"]
    assert _count_rows(conn, "asset_events") == 0
    assert _count_rows(conn, "receipt_queue") == 0


def test_case_detail_start_return_populates_queue_without_events_or_receipts(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 30, "CASE-R", 1)
    _insert_asset(conn, "RETURN-READY", location_type="IN_CUSTODY", holder_id=1, home_slot_id=30)
    conn.commit()

    response = client.post(
        "/dashboard/cases/CASE-R/queue",
        data={"workflow_action": "return", "asset_tag": "RETURN-READY"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/return")
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["RETURN-READY"]
    assert _count_rows(conn, "asset_events") == 0
    assert _count_rows(conn, "receipt_queue") == 0


def test_case_detail_rejects_stale_or_ineligible_issue_selection(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 40, "CASE-STALE", 1)
    asset_id = _insert_asset(conn, "STALE-ISSUE", location_type="IN_CUSTODY", holder_id=1, home_slot_id=40)
    _occupy_slot(conn, 40, asset_id)
    conn.commit()

    response = client.post(
        "/dashboard/cases/CASE-STALE/queue",
        data={"workflow_action": "issue", "asset_tag": "STALE-ISSUE"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Queue not started." in response.data
    assert intake_app.SCAN_QUEUE == []
    assert _count_rows(conn, "asset_events") == 0
    assert _count_rows(conn, "receipt_queue") == 0


def test_case_detail_mixed_issue_selection_does_not_queue_partial_batch(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 50, "CASE-MIX", 1)
    _insert_slot(conn, 51, "CASE-MIX", 2)
    ready_asset_id = _insert_asset(conn, "MIX-READY", location_type="STORAGE", home_slot_id=50)
    blocked_asset_id = _insert_asset(conn, "MIX-BLOCKED", location_type="IN_CUSTODY", holder_id=1, home_slot_id=51)
    _occupy_slot(conn, 50, ready_asset_id)
    _occupy_slot(conn, 51, blocked_asset_id)
    conn.commit()

    response = client.post(
        "/dashboard/cases/CASE-MIX/queue",
        data={"workflow_action": "issue", "asset_tag": ["MIX-READY", "MIX-BLOCKED"]},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Queue not started." in response.data
    assert intake_app.SCAN_QUEUE == []
    assert _count_rows(conn, "asset_events") == 0
    assert _count_rows(conn, "receipt_queue") == 0


def test_case_detail_blocks_return_when_issue_queue_exists(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 60, "CASE-BLOCK", 1)
    _insert_slot(conn, 61, "CASE-BLOCK", 2)
    issue_asset_id = _insert_asset(conn, "BLOCK-ISSUE", location_type="STORAGE", home_slot_id=60)
    _insert_asset(conn, "BLOCK-RETURN", location_type="IN_CUSTODY", holder_id=1, home_slot_id=61)
    _occupy_slot(conn, 60, issue_asset_id)
    conn.commit()

    issue_response = client.post(
        "/dashboard/cases/CASE-BLOCK/queue",
        data={"workflow_action": "issue", "asset_tag": "BLOCK-ISSUE"},
        follow_redirects=False,
    )
    assert issue_response.status_code == 302
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["BLOCK-ISSUE"]

    return_response = client.post(
        "/dashboard/cases/CASE-BLOCK/queue",
        data={"workflow_action": "return", "asset_tag": "BLOCK-RETURN"},
        follow_redirects=True,
    )

    assert return_response.status_code == 200
    assert b"Finish or clear the current queue before starting a different action." in return_response.data
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["BLOCK-ISSUE"]
    assert _count_rows(conn, "asset_events") == 0
    assert _count_rows(conn, "receipt_queue") == 0


def test_case_detail_blocks_issue_when_return_queue_exists(app_client) -> None:
    conn, client = app_client
    _insert_slot(conn, 70, "CASE-BLOCK-R", 1)
    _insert_slot(conn, 71, "CASE-BLOCK-R", 2)
    issue_asset_id = _insert_asset(conn, "BLOCK-R-ISSUE", location_type="STORAGE", home_slot_id=70)
    _insert_asset(conn, "BLOCK-R-RETURN", location_type="IN_CUSTODY", holder_id=1, home_slot_id=71)
    _occupy_slot(conn, 70, issue_asset_id)
    conn.commit()

    return_response = client.post(
        "/dashboard/cases/CASE-BLOCK-R/queue",
        data={"workflow_action": "return", "asset_tag": "BLOCK-R-RETURN"},
        follow_redirects=False,
    )
    assert return_response.status_code == 302
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["BLOCK-R-RETURN"]

    issue_response = client.post(
        "/dashboard/cases/CASE-BLOCK-R/queue",
        data={"workflow_action": "issue", "asset_tag": "BLOCK-R-ISSUE"},
        follow_redirects=True,
    )

    assert issue_response.status_code == 200
    assert b"Finish or clear the current queue before starting a different action." in issue_response.data
    assert [scan.asset_tag for scan in intake_app.SCAN_QUEUE] == ["BLOCK-R-RETURN"]
    assert _count_rows(conn, "asset_events") == 0
    assert _count_rows(conn, "receipt_queue") == 0


def test_holders_and_cases_deterministic_ordering(app_client) -> None:
    conn, _ = app_client
    _insert_holder(conn, 1, "Bravo")
    _insert_holder(conn, 2, "Alpha")
    _insert_asset(conn, "A-1", location_type="IN_CUSTODY", holder_id=1)
    _insert_asset(conn, "A-2", location_type="IN_CUSTODY", holder_id=2)

    _insert_slot(conn, 10, "CASE-B", 1)
    _insert_slot(conn, 11, "CASE-A", 1)
    asset_id = _insert_asset(conn, "SLOT-1", location_type="STORAGE")
    conn.execute(
        """
        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
        VALUES (10, ?, '2026-01-01T00:00:00Z');
        """,
        (asset_id,),
    )
    conn.commit()

    holders = list_holders_in_custody(conn)
    assert [row["holder_name"] for row in holders] == ["Alpha", "Bravo"]

    cases = list_case_summaries(conn)
    assert [row["case_name"] for row in cases] == ["CASE-A", "CASE-B"]


def test_case_summaries_sort_case_numbers_naturally(app_client) -> None:
    conn, _ = app_client
    _insert_slot(conn, 10, "CASE-13", 1)
    _insert_slot(conn, 11, "CASE-2", 1)
    _insert_slot(conn, 12, "CASE-111", 1)
    _insert_slot(conn, 13, "CASE-1", 1)
    _insert_slot(conn, 14, "CASE-16", 1)
    conn.commit()

    cases = list_case_summaries(conn)

    assert [row["case_name"] for row in cases] == ["CASE-1", "CASE-2", "CASE-13", "CASE-16", "CASE-111"]


def test_holder_detail_uses_most_recent_issue_event_and_unknown_when_missing(app_client) -> None:
    conn, _ = app_client
    _insert_holder(conn, 1, "Holder", organization="Operations")
    _insert_asset(
        conn,
        "AT-RECENT",
        location_type="IN_CUSTODY",
        holder_id=1,
        equipment_type="laptop",
        manufacturer="Dell",
        model="XPS",
    )
    _insert_asset(
        conn,
        "AT-UNKNOWN",
        location_type="IN_CUSTODY",
        holder_id=1,
        equipment_type="tablet",
    )
    _insert_issue_event(conn, "AT-RECENT", "2026-01-01T00:00:00Z", legacy=True)
    _insert_issue_event(conn, "AT-RECENT", "2026-02-01T00:00:00Z")
    conn.commit()

    detail = get_holder_custody_detail(
        conn,
        1,
        now_utc=datetime(2026, 2, 20, 0, 0, 0, tzinfo=timezone.utc),
    )
    assert detail is not None
    assert detail["organization"] == "Operations"

    rows = {row["asset_tag"]: row for row in detail["assets"]}
    assert rows["AT-RECENT"]["last_issued_date"] == "2026-02-01T00:00:00Z"
    assert rows["AT-RECENT"]["days_out"] == 19
    assert rows["AT-UNKNOWN"]["last_issued_date"] is None
    assert rows["AT-UNKNOWN"]["days_out"] is None


def test_dashboard_holders_only_lists_holders_with_outstanding_assets_and_shows_organization(app_client) -> None:
    conn, client = app_client
    _insert_holder(conn, 1, "Alpha", organization="Ops")
    _insert_holder(conn, 2, "Bravo", organization="Admin")
    _insert_asset(conn, "AT-1", location_type="IN_CUSTODY", holder_id=1)
    _insert_asset(conn, "AT-2", location_type="STORAGE", holder_id=2)
    conn.commit()

    response = client.get("/dashboard/holders")

    assert response.status_code == 200
    assert b"Alpha" in response.data
    assert b"Ops" in response.data
    assert b"Bravo" not in response.data
    assert b"Admin" not in response.data


def test_dashboard_holder_detail_shows_organization_and_outstanding_count(app_client) -> None:
    conn, client = app_client
    _insert_holder(conn, 1, "Field Team", organization="Ops")
    _insert_asset(conn, "AT-100", location_type="IN_CUSTODY", holder_id=1)
    _insert_asset(conn, "AT-101", location_type="IN_CUSTODY", holder_id=1)
    conn.commit()

    response = client.get("/dashboard/holders/1")

    assert response.status_code == 200
    assert b"Outstanding Assets: Field Team" in response.data
    assert b"Organization:</strong> Ops" in response.data
    assert b"Outstanding Assets:</strong> 2" in response.data
    assert b"AT-100" in response.data
    assert b"AT-101" in response.data

def _assert_rendered_order(rendered: bytes, *needles: bytes) -> None:
    positions = [rendered.index(needle) for needle in needles]
    assert positions == sorted(positions)


def test_dashboard_case_list_renders_cases_in_natural_numeric_order(app_client) -> None:
    conn, client = app_client
    for slot_id, case_name in enumerate(["CASE-10", "CASE-2", "CASE-9", "CASE-1"], start=1000):
        _insert_slot(conn, slot_id, case_name, 1)
    conn.commit()

    response = client.get("/dashboard/cases")

    assert response.status_code == 200
    _assert_rendered_order(
        response.data,
        b'href="/dashboard/cases/CASE-1"',
        b'href="/dashboard/cases/CASE-2"',
        b'href="/dashboard/cases/CASE-9"',
        b'href="/dashboard/cases/CASE-10"',
    )


def test_case_inventory_dropdown_renders_cases_in_natural_numeric_order(app_client) -> None:
    conn, client = app_client
    for slot_id, case_name in enumerate(["CASE-10", "CASE-2", "CASE-9", "CASE-1"], start=1100):
        _insert_slot(conn, slot_id, case_name, 1)
    conn.commit()

    response = client.get("/report/case-inventory")

    assert response.status_code == 200
    _assert_rendered_order(
        response.data,
        b'<option value="CASE-1"',
        b'<option value="CASE-2"',
        b'<option value="CASE-9"',
        b'<option value="CASE-10"',
    )


def test_dashboard_case_detail_renders_slots_in_numeric_order(app_client) -> None:
    conn, client = app_client
    for slot_id, slot_position in [(1201, 10), (1202, 2), (1203, 9), (1204, 1)]:
        _insert_slot(conn, slot_id, "CASE-SLOTS", slot_position)
    conn.commit()

    response = client.get("/dashboard/cases/CASE-SLOTS")

    assert response.status_code == 200
    _assert_rendered_order(response.data, b">1</td>", b">2</td>", b">9</td>", b">10</td>")
