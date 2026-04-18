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
    conn.execute(
        """
        INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
        VALUES (101, 'CASE-1', 1, NULL);
        """
    )
    conn.execute(
        """
        INSERT INTO assets (
            id, asset_tag, serial_number, equipment_type, manufacturer, model,
            location_type, current_holder_id, home_slot_id
        )
        VALUES (
            501, 'LOCK-TAG-1', 'SN-1', 'laptop', 'Dell', 'Latitude',
            'IN_CUSTODY', 1, 101
        );
        """
    )
    conn.commit()
    conn.close()

    intake_app.SCAN_QUEUE.clear()
    intake_app.app.testing = True
    return intake_app.app.test_client()


def _login_with_timeout(client, *, role: str = "admin") -> int:
    user_id = create_test_user(username=f"{role}-timeout-user", password="op-pass", role=role)
    now = intake_app.now_seconds()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["last_seen"] = now
        sess["session_started_at"] = now
    return user_id


def test_add_assets_and_preview_render_timeout_lock_targets(client_with_temp_db) -> None:
    _login_with_timeout(client_with_temp_db)
    intake_app.SCAN_QUEUE.append(Scan.now("LOCK-TAG-NEW"))

    add_assets = client_with_temp_db.get("/add-assets")
    assert add_assets.status_code == 200
    assert add_assets.data.count(b"data-timeout-lock-target") >= 5
    assert b"remaining <= 0 && !timeoutLocked" in add_assets.data

    preview = client_with_temp_db.get("/preview")
    assert preview.status_code == 200
    assert b'id="timeout-lock-panel"' in preview.data
    assert b'id="timeout-lock-state">Active<' in preview.data
    assert b'class="timeout-countdown"' in preview.data
    assert b'remainingSeconds <= 10 && remainingSeconds > 0' in preview.data
    assert b'classList.add("timeout-warning")' in preview.data
    assert b"Session expired. Redirecting to login..." in preview.data
    assert b'let timeoutLocked = false;' in preview.data
    assert b'window.location = "/logout";' in preview.data
    assert b'data-timeout-lock-target>Add to database<' in preview.data
    assert b"Discard batch" not in preview.data
    assert b'action="/preview/discard"' not in preview.data


def test_issue_and_return_flows_render_timeout_lock_targets(client_with_temp_db) -> None:
    _login_with_timeout(client_with_temp_db, role="operator")
    intake_app.SCAN_QUEUE.append(Scan.now("LOCKTAG1"))

    with client_with_temp_db.session_transaction() as sess:
        sess["holder_id"] = 1
        sess["issue_mode"] = True
        sess["issue_building"] = "HQ North"
        sess["issue_room"] = "210"

    issue_queue = client_with_temp_db.get("/issue")
    assert issue_queue.status_code == 200
    assert b'id="timeout-lock-panel"' in issue_queue.data
    assert b"Open Issue Assets Preview / Confirm" in issue_queue.data
    assert issue_queue.data.count(b"data-timeout-lock-target") >= 4

    issue_preview = client_with_temp_db.get("/issue/preview")
    assert issue_preview.status_code == 200
    assert b'id="timeout-lock-panel"' in issue_preview.data
    assert b'data-timeout-lock-target>Commit Issue<' in issue_preview.data
    assert b"Discard batch" not in issue_preview.data
    assert b'action="/preview/discard"' not in issue_preview.data

    return_queue = client_with_temp_db.get("/return")
    assert return_queue.status_code == 200
    assert b'id="timeout-lock-panel"' in return_queue.data
    assert b"Open Return Assets Preview / Confirm" in return_queue.data

    return_preview = client_with_temp_db.get("/return/preview")
    assert return_preview.status_code == 200
    assert b'id="timeout-lock-panel"' in return_preview.data
    assert b'data-timeout-lock-target>Commit Return<' in return_preview.data
    assert b"Discard batch" not in return_preview.data
    assert b'action="/preview/discard"' not in return_preview.data
