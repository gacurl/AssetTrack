from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

import assettrack.db as db
from assettrack.custody_analytics import SUPPORTED_ANALYTICS
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
    operator_id = create_test_user(username="custody-analytics-operator", password="op-pass", role="operator")
    login_session(client, operator_id)


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


def _insert_asset(
    conn: sqlite3.Connection,
    asset_tag: str,
    *,
    equipment_type: str = "laptop",
    location_type: str = "STORAGE",
    current_holder_id: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO assets (
            asset_tag, serial_number, equipment_type, location_type, current_holder_id
        )
        VALUES (?, ?, ?, ?, ?);
        """,
        (asset_tag, f"SER-{asset_tag}", equipment_type, location_type, current_holder_id),
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


def _seed_holder_totals() -> None:
    conn = db.get_connection()
    try:
        _insert_holder(conn, 1, "Alice Holder", "Mission A")
        _insert_holder(conn, 2, "Bob Holder", "Mission B")
        _insert_asset(conn, "ALICE-1", equipment_type="laptop")
        _insert_asset(conn, "ALICE-2", equipment_type="router")
        _insert_asset(conn, "BOB-1", equipment_type="router")
        _insert_event(conn, "ALICE-1", "ISSUE", "2026-01-01T00:00:00Z", holder_id=1)
        _insert_event(conn, "ALICE-1", "RETURN", "2026-01-03T06:00:00Z")
        _insert_event(conn, "ALICE-2", "ISSUE", "2026-01-03T00:00:00Z", holder_id=1)
        _insert_event(conn, "ALICE-2", "RETURN", "2026-01-03T12:00:00Z")
        _insert_event(conn, "BOB-1", "ISSUE", "2026-01-04T00:00:00Z", holder_id=2)
        _insert_event(conn, "BOB-1", "RETURN", "2026-01-04T01:00:00Z")
        conn.commit()
    finally:
        conn.close()


def _seed_accountability() -> None:
    conn = db.get_connection()
    try:
        _insert_holder(conn, 1, "Alice Holder", "Mission A")
        _insert_asset(conn, "IN-1", location_type="STORAGE")
        _insert_event(conn, "IN-1", "ASSET_CREATED", "2026-01-01T00:00:00Z")
        _insert_asset(conn, "OUT-1", location_type="IN_CUSTODY", current_holder_id=1)
        _insert_event(conn, "OUT-1", "ISSUE", "2026-01-02T00:00:00Z", holder_id=1)
        _insert_asset(conn, "BAD-1", location_type="STORAGE", current_holder_id=1)
        _insert_event(conn, "BAD-1", "RETURN", "2026-01-03T00:00:00Z")
        conn.commit()
    finally:
        conn.close()


def _analytics_url(measure: str, grouping: str, chart_type: str) -> str:
    return f"/report/custody-analytics?generate=1&measure={measure}&grouping={grouping}&chart_type={chart_type}"


def _selector_mapping(response) -> list[dict]:
    body = response.data.decode()
    match = re.search(
        r'<script id="analytics-selector-map" type="application/json">(.+?)</script>',
        body,
        flags=re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def _chart_select_html(response) -> str:
    body = response.data.decode()
    match = re.search(r'<select name="chart_type" id="analytics-chart-type">(.+?)</select>', body, flags=re.DOTALL)
    assert match is not None
    return match.group(1)


def test_reports_exposes_custody_analytics(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)

    response = client_with_temp_db.get("/report")

    assert response.status_code == 200
    assert b'href="/report/custody-analytics"' in response.data
    assert b"Custody Analytics" in response.data


def test_dashboard_route_renders_and_lists_31_39a_selections(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)

    response = client_with_temp_db.get("/report/custody-analytics")

    assert response.status_code == 200
    assert b"Measure" in response.data
    assert b"Group By" in response.data
    assert b"Chart Type" in response.data
    for selection in SUPPORTED_ANALYTICS:
        assert selection.label.encode() in response.data


def test_dashboard_exposes_authoritative_selector_mapping(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)

    response = client_with_temp_db.get("/report/custody-analytics")
    mapping = _selector_mapping(response)

    assert response.status_code == 200
    assert {(item["measure"], item["grouping"]) for item in mapping} == {
        (selection.measure, selection.grouping) for selection in SUPPORTED_ANALYTICS
    }
    assert b"analytics-measure" in response.data
    assert b"analytics-grouping" in response.data
    assert b"analytics-chart-type" in response.data


def test_selector_mapping_has_expected_chart_types(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)

    mapping = {
        (item["measure"], item["grouping"]): item["charts"]
        for item in _selector_mapping(client_with_temp_db.get("/report/custody-analytics"))
    }

    assert mapping[("checkout_transactions", "checkout_date")] == [{"label": "Line", "value": "line"}]
    assert mapping[("checkout_duration", "duration_range")] == [{"label": "Histogram", "value": "histogram"}]


def test_valid_selection_does_not_render_stale_chart_type(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)

    response = client_with_temp_db.get("/report/custody-analytics?measure=checkout_transactions&grouping=checkout_date")
    chart_select = _chart_select_html(response)

    assert response.status_code == 200
    assert 'value="line" selected' in chart_select
    assert "Histogram" not in chart_select


def test_total_checkout_time_by_holder_renders(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)
    _seed_holder_totals()

    response = client_with_temp_db.get(_analytics_url("total_time_checked_out", "holder", "bar"))

    assert response.status_code == 200
    assert b"Total Time Checked Out + MA / Holder" in response.data
    assert b"Alice Holder (Mission A)" in response.data
    assert b"2d 18h" in response.data
    assert b"Bob Holder (Mission B)" in response.data
    assert b"1h" in response.data


def test_duration_distribution_renders_31_39a_buckets(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)
    _seed_holder_totals()

    response = client_with_temp_db.get(_analytics_url("checkout_duration", "duration_range", "histogram"))

    assert response.status_code == 200
    for label in (b"&lt; 8 hours", b"8 to &lt;24 hours", b"1 to &lt;3 days", b"3 to &lt;7 days", b"7+ days"):
        assert label in response.data
    assert b"Histogram" in response.data


def test_current_accountability_renders_31_39a_totals(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)
    _seed_accountability()

    response = client_with_temp_db.get(_analytics_url("current_accountability", "accountability_state", "bar"))

    assert response.status_code == 200
    assert b"Current Accountability + Accountability State" in response.data
    assert b"Checked In" in response.data
    assert b"Checked Out" in response.data
    assert b"Exceptions / Unresolved" in response.data


def test_checkout_activity_by_day_is_chronological(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)
    _seed_holder_totals()

    response = client_with_temp_db.get(_analytics_url("checkout_transactions", "checkout_date", "line"))

    assert response.status_code == 200
    body = response.data.decode()
    assert "Line" in body
    assert body.index("2026-01-01") < body.index("2026-01-03") < body.index("2026-01-04")


def test_unsupported_measure_grouping_and_chart_requests_are_rejected(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)

    unsupported_combo = client_with_temp_db.get(_analytics_url("total_time_checked_out", "asset_type", "bar"))
    unsupported_chart = client_with_temp_db.get(_analytics_url("checkout_transactions", "checkout_date", "bar"))

    assert unsupported_combo.status_code == 400
    assert b"Unsupported Measure and Group By combination." in unsupported_combo.data
    assert unsupported_chart.status_code == 400
    assert b"Unsupported chart type" in unsupported_chart.data


def test_zero_result_dataset_displays_cleanly(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)

    response = client_with_temp_db.get(_analytics_url("total_time_checked_out", "holder", "bar"))

    assert response.status_code == 200
    assert b"No analytics results for this selection." in response.data


def test_rendering_does_not_modify_assettrack_state(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)
    _seed_holder_totals()
    conn = db.get_connection()
    before = _snapshot(conn)
    conn.close()

    response = client_with_temp_db.get(_analytics_url("total_time_checked_out", "holder", "bar"))

    conn = db.get_connection()
    after = _snapshot(conn)
    conn.close()
    assert response.status_code == 200
    assert before == after


def test_existing_custody_accountability_report_still_renders(client_with_temp_db) -> None:
    _login_operator(client_with_temp_db)
    _seed_holder_totals()

    response = client_with_temp_db.get("/report/custody-accountability")

    assert response.status_code == 200
    assert b"Asset Custody / Accountability" in response.data
    assert b"Holder / MA Accountability" in response.data
