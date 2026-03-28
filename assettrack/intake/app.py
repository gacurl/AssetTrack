# assettrack/intake/app.py
"""
Issue 4-1+: Local Intake UI (Keyboard Wedge)

Feynman-brief:
- Scanner acts like a keyboard.
- Browser input box receives the "typed" barcode + Enter.
- We store scans in an in-memory list (queue) and echo them back.
- Preview/validate/commit are separate steps; commit is atomic.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for

import assettrack.db as db_module
from assettrack.assets import get_asset_table_columns
from assettrack.dashboard import build_dashboard_data, get_custody_days_threshold
from assettrack.db import assert_schema_present, get_connection, initialize_schema
from assettrack.drilldowns import (
    get_case_slot_detail,
    get_holder_custody_detail,
    list_case_summaries,
    list_holders_in_custody,
)
from assettrack.ingest.validator import validate_rows
from assettrack.ingest.committer import BatchCommitError, commit_batch
from assettrack.intake.scan import Scan
from assettrack.intake.to_ingest import scan_to_ingest_row
from assettrack.auth import current_user, require_login, require_role
from assettrack.holders import create_holder, get_holder, list_holders, search_holders, update_holder
from assettrack.reference_data import (
    create_building,
    create_organization,
    create_organization_building_mapping,
    list_buildings,
    list_organization_building_mappings,
    list_organizations,
)
from assettrack.audit import record_event
from assettrack.event_types import ISSUE_EVENT_TYPE, RETURN_EVENT_TYPE
from assettrack.users import (
    change_own_password,
    count_users,
    create_user,
    get_user_by_id,
    get_user_by_username,
    list_users,
    reset_user_password,
    set_user_active,
    set_user_role,
    verify_password,
)


app = Flask(__name__)
app.secret_key = os.getenv("ASSETTRACK_SECRET_KEY", "dev-not-secret")

initialize_schema(db_module.DB_PATH)
assert_schema_present(db_module.DB_PATH)

# In-memory only: wiped on restart
SCAN_QUEUE: list[Scan] = []

INTAKE_TIMEOUT_SECONDS = int(os.getenv("ASSETTRACK_INTAKE_TIMEOUT_SECONDS", "300"))  # default 5 min
TERMINAL_LOCATION_TYPE = "DISPOSED"
TERMINAL_LOCATION_TYPES = {"DISPOSED", "RETIRED"}
RETIRE_FAILURE_TYPES = {"HARDWARE", "LOST", "STOLEN", "DESTROYED", "OTHER"}
ASSET_EQUIPMENT_TYPE_OPTIONS = ("laptop", "tablet")


@app.after_request
def refresh_session_activity(response):
    if _should_refresh_session_activity():
        touch_session()
    return response


@app.context_processor
def inject_auth_user():
    user = current_user()
    return {
        "authenticated_user": user,
        "authenticated_role": None if user is None else user.get("role"),
        "case_status_summary": _case_status_summary,
        "holder_display_name": _holder_display_name,
        "holder_display_type": _holder_display_type,
    }


# Helpers

def now_seconds() -> int:
    return int(time.time())


def touch_session() -> None:
    session["last_seen"] = now_seconds()


def _should_refresh_session_activity() -> bool:
    if current_user() is None:
        return False

    endpoint = str(request.endpoint or "").strip()
    if endpoint in {"logout", "static"}:
        return False

    return True


def sanitize_scan(raw: str) -> str:
    """Keep only letters and numbers; drop tabs/newlines/suffix junk."""
    return "".join(ch for ch in raw if ch.isalnum()).upper()


def _queue_contains_asset_tag(asset_tag: str) -> bool:
    normalized = sanitize_scan(asset_tag or "")
    if not normalized:
        return False

    for queued in SCAN_QUEUE:
        if sanitize_scan(queued.asset_tag or "") == normalized:
            return True
    return False


def auth_enabled() -> bool:
    return False


def is_authed() -> bool:
    return current_user() is not None


def set_authed(value: bool) -> None:
    if value:
        return
    session.pop("user_id", None)
    session.pop("last_seen", None)


def auth_ok(submitted: str | None) -> bool:
    return False


def enforce_inactivity_timeout() -> bool:
    return is_authed()


def seconds_since_last_seen() -> Optional[int]:
    last_seen = session.get("last_seen")
    if last_seen is None:
        return None
    return max(0, now_seconds() - int(last_seen))


def build_parsed_rows_from_queue() -> list[dict]:
    """
    Build rows in the validator/committer format:
      [{"row_number": 1, "data": {...}}, ...]
    Each queued Scan already carries its own equipment_type.
    """
    rows: list[dict] = []

    for idx, s in enumerate(SCAN_QUEUE):
        data = scan_to_ingest_row(s)
        rows.append({"row_number": idx + 1, "data": data})

    return rows


def wants_json() -> bool:
    """
    Simple switch so curl/automation can still get JSON:
      /preview?json=1
      /preview/commit?json=1 (POST)
    """
    return (request.args.get("json") or "").strip() == "1"


def _normalize_location_type(value: object) -> str:
    return str(value or "").strip().upper()


def _is_terminal_location_type(value: object) -> bool:
    return _normalize_location_type(value) in TERMINAL_LOCATION_TYPES


def _get_event_by_id(conn: sqlite3.Connection, event_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT
            id,
            asset_tag,
            event_type,
            event_date,
            actor,
            notes,
            payload,
            supersedes_event_id,
            correction_reason
        FROM asset_events
        WHERE id = ?;
        """,
        (event_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _event_already_superseded(conn: sqlite3.Connection, event_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM asset_events
        WHERE supersedes_event_id = ?
        LIMIT 1;
        """,
        (event_id,),
    ).fetchone()
    return row is not None


def _find_asset_for_scan_tag(conn, scan_tag: str) -> Optional[dict]:
    t = (scan_tag or "").strip()
    if not t:
        return None

    rows = conn.execute(
        """
        SELECT *
        FROM assets
        WHERE UPPER(asset_tag) = UPPER(?)
           OR REPLACE(UPPER(asset_tag), '-', '') = UPPER(?)
        LIMIT 2;
        """,
        (t, t),
    ).fetchall()

    if not rows:
        return None

    if len(rows) > 1 and str(rows[0]["asset_tag"]) != str(rows[1]["asset_tag"]):
        raise ValueError(f"Ambiguous asset_tag match for scan '{t}'")

    return dict(rows[0])


def _find_case_assets_for_scan_tag(conn, scan_tag: str) -> Optional[dict]:
    t = (scan_tag or "").strip()
    if not t:
        return None

    slot_rows = conn.execute(
        """
        SELECT id, case_name, slot_position, current_asset_tag
        FROM slots
        WHERE UPPER(case_name) = UPPER(?)
           OR REPLACE(UPPER(case_name), '-', '') = UPPER(?)
        ORDER BY slot_position ASC, id ASC;
        """,
        (t, t),
    ).fetchall()
    if not slot_rows:
        return None

    case_names = {str(row["case_name"] or "").strip().upper() for row in slot_rows if str(row["case_name"] or "").strip()}
    if len(case_names) > 1:
        raise ValueError(f"Ambiguous case match for scan '{t}'")

    case_name = str(slot_rows[0]["case_name"] or "").strip().upper()
    assets: list[dict] = []
    seen_asset_tags: set[str] = set()

    for slot_row in slot_rows:
        slot_id = int(slot_row["id"])
        slot_position = int(slot_row["slot_position"])
        asset_tag = ""

        occupancy_row = conn.execute(
            """
            SELECT a.asset_tag
            FROM slot_occupancy so
            JOIN assets a ON a.id = so.asset_id
            WHERE so.slot_id = ?
            ORDER BY so.id ASC
            LIMIT 1;
            """,
            (slot_id,),
        ).fetchone()
        if occupancy_row is not None:
            asset_tag = sanitize_scan(str(occupancy_row["asset_tag"] or ""))
        else:
            legacy_asset_tag = str(slot_row["current_asset_tag"] or "").strip()
            if legacy_asset_tag:
                asset_row = _find_asset_for_scan_tag(conn, legacy_asset_tag)
                if asset_row is not None:
                    asset_tag = sanitize_scan(str(asset_row["asset_tag"] or ""))

        if not asset_tag or asset_tag in seen_asset_tags:
            continue

        seen_asset_tags.add(asset_tag)
        assets.append(
            {
                "asset_tag": asset_tag,
                "home_slot_id": slot_id,
                "case_name": case_name,
                "slot_position": slot_position,
            }
        )

    return {
        "case_name": case_name,
        "assets": assets,
    }


def _asset_current_slot(conn, asset_id: int, asset_tag: str) -> Optional[dict]:
    occupancy_row = conn.execute(
        """
        SELECT s.id AS slot_id, s.case_name, s.slot_position
        FROM slot_occupancy so
        JOIN slots s ON s.id = so.slot_id
        WHERE so.asset_id = ?
        LIMIT 1;
        """,
        (asset_id,),
    ).fetchone()
    if occupancy_row:
        return dict(occupancy_row)

    legacy_row = conn.execute(
        """
        SELECT id AS slot_id, case_name, slot_position
        FROM slots
        WHERE UPPER(current_asset_tag) = UPPER(?)
           OR REPLACE(UPPER(current_asset_tag), '-', '') = UPPER(?)
        LIMIT 1;
        """,
        (asset_tag, asset_tag),
    ).fetchone()
    return dict(legacy_row) if legacy_row else None


def _asset_home_slot(conn, home_slot_id: object) -> Optional[dict]:
    if home_slot_id is None:
        return None
    row = conn.execute(
        """
        SELECT id AS slot_id, case_name, slot_position
        FROM slots
        WHERE id = ?
        LIMIT 1;
        """,
        (int(home_slot_id),),
    ).fetchone()
    return dict(row) if row else None


def _list_slot_options(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            s.id,
            s.case_name,
            s.slot_position,
            so.asset_id AS occupied_asset_id,
            a.asset_tag AS occupied_asset_tag,
            s.current_asset_tag AS legacy_asset_tag
        FROM slots s
        LEFT JOIN slot_occupancy so ON so.slot_id = s.id
        LEFT JOIN assets a ON a.id = so.asset_id
        ORDER BY UPPER(s.case_name) ASC, s.slot_position ASC, s.id ASC;
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "case_name": str(row["case_name"] or ""),
            "slot_position": int(row["slot_position"]),
            "occupied_asset_id": None if row["occupied_asset_id"] is None else int(row["occupied_asset_id"]),
            "occupied_asset_tag": str(row["occupied_asset_tag"] or row["legacy_asset_tag"] or ""),
        }
        for row in rows
    ]


def _slot_case_options(slot_options: list[dict]) -> list[str]:
    return sorted({str(row["case_name"]) for row in slot_options if str(row["case_name"]).strip()})


def _resolve_slot_selection(
    conn: sqlite3.Connection,
    *,
    case_name: str,
    slot_id_raw: str,
) -> tuple[Optional[dict], list[str]]:
    case_name_clean = str(case_name or "").strip().upper()
    slot_id_text = str(slot_id_raw or "").strip()
    errors: list[str] = []

    if bool(case_name_clean) != bool(slot_id_text):
        errors.append("case and slot must both be selected.")
        return None, errors

    if not case_name_clean and not slot_id_text:
        return None, errors

    try:
        slot_id = int(slot_id_text)
    except ValueError:
        errors.append("slot selection is invalid.")
        return None, errors

    slot_row = conn.execute(
        """
        SELECT id, case_name, slot_position, current_asset_tag
        FROM slots
        WHERE id = ?
        LIMIT 1;
        """,
        (slot_id,),
    ).fetchone()
    if slot_row is None:
        errors.append("selected slot does not exist.")
        return None, errors

    resolved_case = str(slot_row["case_name"] or "").strip().upper()
    if resolved_case != case_name_clean:
        errors.append("selected slot does not belong to the selected case.")
        return None, errors

    return dict(slot_row), errors


def _validate_admin_new_asset_form(
    conn: sqlite3.Connection,
    form_state: dict[str, str],
) -> tuple[Optional[dict], list[str]]:
    errors: list[str] = []

    if not form_state["asset_tag"]:
        errors.append("Enter an asset tag.")
    if not form_state["serial_number"]:
        errors.append("Enter a serial number.")
    if not form_state["manufacturer"]:
        errors.append("Enter a manufacturer.")
    if not form_state["equipment_type"]:
        errors.append("Choose an asset type.")
    elif form_state["equipment_type"] not in ASSET_EQUIPMENT_TYPE_OPTIONS:
        errors.append("Choose a valid asset type.")
    if not form_state["building"]:
        errors.append("Enter the building.")
    if not form_state["room"]:
        errors.append("Enter the room.")

    selected_slot, slot_errors = _resolve_slot_selection(
        conn,
        case_name=form_state["case_name"],
        slot_id_raw=form_state["slot_id"],
    )
    slot_error_map = {
        "case and slot must both be selected.": "Choose both a case and a slot, or leave both blank.",
        "slot selection is invalid.": "Choose a valid slot.",
        "selected slot does not exist.": "Choose a slot that exists.",
        "selected slot does not belong to the selected case.": "Choose a slot in the selected case.",
    }
    errors.extend(slot_error_map.get(error, error) for error in slot_errors)

    return selected_slot, errors


def _humanize_admin_asset_create_error(error_message: str) -> str:
    error_map = {
        "asset_tag already exists.": "Asset tag already exists.",
        "serial_number already exists.": "Serial number already exists.",
        "Slot not found for case_number + slot_number.": "The selected slot no longer exists.",
        "Selected slot is already occupied.": "The selected slot is already occupied.",
    }
    return error_map.get(error_message, error_message)


def _asset_state_label(location_type: object) -> str:
    normalized = _normalize_location_type(location_type)
    if normalized == "STORAGE":
        return "In storage"
    if normalized == "IN_CUSTODY":
        return "In custody"
    if normalized in TERMINAL_LOCATION_TYPES:
        return "Retired / disposed"
    if not normalized:
        return "Unknown"
    return normalized.replace("_", " ").title()


def _resolved_runtime_db_path() -> Path:
    return db_module.DB_PATH.expanduser().resolve()


def _case_status_summary(total_slots: object, occupied_slots: object) -> dict[str, object]:
    total = int(total_slots or 0)
    occupied = int(occupied_slots or 0)
    available = max(0, total - occupied)

    if available == 0:
        return {
            "label": "FULL",
            "text": "FULL - No space",
            "class_name": "full",
            "available_slots": available,
        }
    if available <= 3:
        return {
            "label": "LOW",
            "text": "LOW - Getting tight",
            "class_name": "low",
            "available_slots": available,
        }
    return {
        "label": "OPEN",
        "text": "OPEN - Use now",
        "class_name": "open",
        "available_slots": available,
    }


def _queue_redirect_target(return_to: str) -> str:
    target = str(return_to or "").strip()
    if not target.startswith("/") or target.startswith("//"):
        return target

    path, sep, fragment = target.partition("#")
    if path == "/return" and not fragment:
        return f"{path}#queue-section"
    return target


def _return_to_path(return_to: str) -> str:
    target = str(return_to or "").strip()
    if not target.startswith("/") or target.startswith("//"):
        return target
    path, _, _ = target.partition("#")
    return path


def _safe_local_return_to(return_to: str) -> str | None:
    target = str(return_to or "").strip()
    if target.startswith("/") and not target.startswith("//"):
        return target
    return None


def _holder_form_error_message(exc: ValueError) -> str:
    message = str(exc)
    if message == "organization is required":
        return "Choose an organization for this holder."
    if message == "name is required":
        return "Enter a person or group name when using Ad Hoc."
    return message


def _holder_display_name(holder: Optional[dict]) -> str:
    if not holder:
        return ""

    name = str(holder.get("name") or "").strip()
    organization = str(holder.get("organization") or "").strip()
    return name or organization


def _holder_display_type(holder: Optional[dict]) -> str:
    if not holder:
        return ""

    holder_type = str(holder.get("holder_type") or "").strip().upper()
    if holder_type == "ORGANIZATION":
        return "Group / organization"
    if holder_type == "PERSON":
        return "Person"
    return holder_type.replace("_", " ").title()


def _lookup_asset_for_verification(
    conn: sqlite3.Connection,
    *,
    asset_tag: str,
    serial_number: str,
) -> tuple[list[dict], Optional[str], str]:
    asset_tag_clean = str(asset_tag or "").strip().upper()
    serial_clean = str(serial_number or "").strip()

    if not asset_tag_clean and not serial_clean:
        return [], "Enter an asset tag or serial number.", "none"

    lookup_mode = "asset_tag" if asset_tag_clean else "serial_number"
    query_value = asset_tag_clean if lookup_mode == "asset_tag" else serial_clean
    like_pattern = f"%{query_value}%"

    if lookup_mode == "asset_tag":
        rows = conn.execute(
            """
            SELECT
                a.*,
                h.id AS holder_record_id,
                h.holder_type AS holder_record_type,
                h.name AS holder_record_name,
                h.organization AS holder_record_organization
            FROM assets a
            LEFT JOIN holders h
              ON h.id = a.current_holder_id
            WHERE UPPER(a.asset_tag) LIKE UPPER(?)
            ORDER BY
                CASE WHEN UPPER(a.asset_tag) = UPPER(?) THEN 0 ELSE 1 END,
                UPPER(a.asset_tag) ASC,
                a.id ASC
            LIMIT 25;
            """,
            (like_pattern, asset_tag_clean),
        ).fetchall()
        if not rows:
            return [], "Asset not found.", lookup_mode
    else:
        rows = conn.execute(
            """
            SELECT
                a.*,
                h.id AS holder_record_id,
                h.holder_type AS holder_record_type,
                h.name AS holder_record_name,
                h.organization AS holder_record_organization
            FROM assets a
            LEFT JOIN holders h
              ON h.id = a.current_holder_id
            WHERE TRIM(COALESCE(serial_number, '')) <> ''
              AND UPPER(a.serial_number) LIKE UPPER(?)
            ORDER BY
                CASE WHEN UPPER(a.serial_number) = UPPER(?) THEN 0 ELSE 1 END,
                UPPER(a.serial_number) ASC,
                UPPER(a.asset_tag) ASC,
                a.id ASC
            LIMIT 25;
            """,
            (like_pattern, serial_clean),
        ).fetchall()
        if not rows:
            return [], "Asset not found.", lookup_mode

    results: list[dict] = []
    for raw_row in rows:
        asset = dict(raw_row)
        home_slot = _asset_home_slot(conn, asset.get("home_slot_id"))
        holder_row = None
        if asset.get("holder_record_id") is not None:
            holder_row = {
                "id": int(asset["holder_record_id"]),
                "holder_type": str(asset.get("holder_record_type") or ""),
                "name": str(asset.get("holder_record_name") or ""),
                "organization": str(asset.get("holder_record_organization") or ""),
            }
        holder_label = ""
        if holder_row is not None:
            holder_name = str(holder_row.get("name") or "").strip()
            holder_org = str(holder_row.get("organization") or "").strip()
            if holder_name and holder_org and holder_org != holder_name:
                holder_label = f"{holder_name} ({holder_org})"
            else:
                holder_label = _holder_display_name(holder_row)

        results.append(
            {
                "id": int(asset["id"]),
                "asset_tag": str(asset.get("asset_tag") or ""),
                "serial_number": str(asset.get("serial_number") or ""),
                "location_type": _normalize_location_type(asset.get("location_type")),
                "state_label": _asset_state_label(asset.get("location_type")),
                "holder_label": holder_label,
                "home_case_name": "" if home_slot is None else str(home_slot.get("case_name") or ""),
                "home_slot_position": None if home_slot is None else int(home_slot["slot_position"]),
            }
        )

    return (results, None, lookup_mode)


def _build_admin_assign_asset_view(conn, scan_tag: str) -> tuple[Optional[dict], list[str]]:
    errors: list[str] = []
    asset = _find_asset_for_scan_tag(conn, scan_tag)
    if not asset:
        return None, ["asset_tag not found"]

    holder_label = "None"
    holder_id = asset.get("current_holder_id")
    if holder_id is not None:
        holder = conn.execute(
            """
            SELECT id, name, identifier
            FROM holders
            WHERE id = ?;
            """,
            (holder_id,),
        ).fetchone()
        if holder:
            identifier = (holder["identifier"] or "").strip()
            holder_label = f"{holder['name']} ({identifier})" if identifier else str(holder["name"])
        else:
            holder_label = f"ID {holder_id}"

    location_type = _normalize_location_type(asset.get("location_type"))
    if _is_terminal_location_type(location_type):
        errors.append("Asset is retired/disposed and cannot be assigned to a slot.")
    if location_type != "STORAGE":
        errors.append("Asset must be location_type=STORAGE.")
    if location_type == "IN_CUSTODY":
        errors.append("Asset is IN_CUSTODY and cannot be assigned to a slot.")

    current_slot = _asset_current_slot(conn, int(asset["id"]), str(asset["asset_tag"]))
    if current_slot:
        errors.append("Asset is already slotted.")

    view = {
        "id": int(asset["id"]),
        "asset_tag": str(asset.get("asset_tag") or ""),
        "manufacturer": str(asset.get("manufacturer") or ""),
        "model": str(asset.get("model") or ""),
        "serial": str(asset.get("serial_number") or ""),
        "location_type": str(asset.get("location_type") or ""),
        "current_holder": holder_label,
        "current_slot": current_slot,
        "home_slot_id": asset.get("home_slot_id"),
    }
    return view, errors


def _build_admin_edit_asset_view(conn, scan_tag: str) -> tuple[Optional[dict], list[str]]:
    asset = _find_asset_for_scan_tag(conn, scan_tag)
    if not asset:
        return None, ["asset_tag not found"]

    location_type = _normalize_location_type(asset.get("location_type"))
    if _is_terminal_location_type(location_type):
        return None, ["Asset is retired/disposed and cannot be edited."]

    current_slot = _asset_current_slot(conn, int(asset["id"]), str(asset["asset_tag"]))
    home_slot = _asset_home_slot(conn, asset.get("home_slot_id"))
    cleanup_state = _build_admin_asset_cleanup_state(conn, asset, current_slot=current_slot)

    return (
        {
            "id": int(asset["id"]),
            "asset_tag": str(asset.get("asset_tag") or ""),
            "serial_number": str(asset.get("serial_number") or ""),
            "manufacturer": str(asset.get("manufacturer") or ""),
            "equipment_type": str(asset.get("equipment_type") or ""),
            "building": str(asset.get("building") or ""),
            "room": str(asset.get("room") or ""),
            "model": str(asset.get("model") or ""),
            "model_code": str(asset.get("model_code") or ""),
            "notes": str(asset.get("notes") or ""),
            "location_type": location_type,
            "current_holder_id": asset.get("current_holder_id"),
            "home_slot_id": asset.get("home_slot_id"),
            "current_slot": current_slot,
            "home_slot": home_slot,
            "cleanup": cleanup_state,
        },
        [],
    )


def _build_admin_asset_cleanup_state(
    conn: sqlite3.Connection,
    asset: dict,
    *,
    current_slot: Optional[dict] = None,
) -> dict:
    reasons: list[str] = []
    asset_tag = str(asset.get("asset_tag") or "").strip()
    if not asset_tag:
        return {"allowed": False, "reasons": ["asset_tag not found"]}

    if conn.execute("SELECT 1 FROM asset_events WHERE asset_tag = ? LIMIT 1;", (asset_tag,)).fetchone():
        reasons.append("Asset has event history and cannot be removed.")

    if current_slot is None:
        current_slot = _asset_current_slot(conn, int(asset["id"]), asset_tag)
    if current_slot is not None:
        reasons.append("Asset has a current slot placement and cannot be removed.")

    if asset.get("home_slot_id") is not None:
        reasons.append("Asset has a home slot assignment and cannot be removed.")

    asset_columns = get_asset_table_columns(conn)
    case_number = str(asset.get("case_number") or "").strip()
    slot_number = str(asset.get("slot_number") or "").strip()
    if "case_number" in asset_columns and case_number:
        reasons.append("Asset still has a case assignment and cannot be removed.")
    if "slot_number" in asset_columns and slot_number:
        reasons.append("Asset still has a slot assignment field and cannot be removed.")

    if asset.get("current_holder_id") is not None:
        reasons.append("Asset is assigned to a holder and cannot be removed.")

    location_type = _normalize_location_type(asset.get("location_type"))
    if location_type in {"STORAGE", "IN_CUSTODY"}:
        reasons.append(f"Asset is in active inventory state {location_type} and cannot be removed.")

    return {"allowed": not reasons, "reasons": reasons}


def _build_admin_slot_move_source_view(conn, slot_id: int) -> Optional[dict]:
    slot_row = conn.execute(
        """
        SELECT id, case_name, slot_position, current_asset_tag
        FROM slots
        WHERE id = ?;
        """,
        (slot_id,),
    ).fetchone()
    if not slot_row:
        return None

    occupancy_row = conn.execute(
        """
        SELECT so.asset_id, a.asset_tag, a.location_type, a.building_room, a.home_slot_id
        FROM slot_occupancy so
        JOIN assets a ON a.id = so.asset_id
        WHERE so.slot_id = ?
        LIMIT 1;
        """,
        (slot_id,),
    ).fetchone()

    occupied = occupancy_row is not None
    asset_view = None
    if occupancy_row:
        asset_view = {
            "asset_id": int(occupancy_row["asset_id"]),
            "asset_tag": str(occupancy_row["asset_tag"] or ""),
            "location_type": str(occupancy_row["location_type"] or ""),
            "building_room": str(occupancy_row["building_room"] or ""),
            "home_slot_id": occupancy_row["home_slot_id"],
        }

    return {
        "slot_id": int(slot_row["id"]),
        "case_name": str(slot_row["case_name"] or ""),
        "slot_position": int(slot_row["slot_position"]),
        "current_asset_tag": str(slot_row["current_asset_tag"] or ""),
        "occupied": occupied,
        "asset": asset_view,
    }


def _build_admin_retire_asset_view(conn, scan_tag: str) -> tuple[Optional[dict], list[str]]:
    asset = _find_asset_for_scan_tag(conn, scan_tag)
    if not asset:
        return None, ["asset_tag not found"]

    location_type = _normalize_location_type(asset.get("location_type"))
    errors: list[str] = []
    if _is_terminal_location_type(location_type):
        errors.append("Asset is already retired/disposed.")
    if location_type not in {"STORAGE", "IN_CUSTODY"}:
        errors.append("Asset must be in STORAGE or IN_CUSTODY to retire.")

    holder_label = "None"
    holder_id = asset.get("current_holder_id")
    if holder_id is not None:
        holder = conn.execute(
            """
            SELECT id, name, identifier
            FROM holders
            WHERE id = ?;
            """,
            (holder_id,),
        ).fetchone()
        if holder:
            identifier = str(holder["identifier"] or "").strip()
            holder_label = f"{holder['name']} ({identifier})" if identifier else str(holder["name"])
        else:
            holder_label = f"ID {holder_id}"

    current_slot = _asset_current_slot(conn, int(asset["id"]), str(asset["asset_tag"]))
    view = {
        "id": int(asset["id"]),
        "asset_tag": str(asset.get("asset_tag") or ""),
        "location_type": location_type,
        "serial_number": str(asset.get("serial_number") or ""),
        "manufacturer": str(asset.get("manufacturer") or ""),
        "model": str(asset.get("model") or ""),
        "current_holder": holder_label,
        "current_holder_id": holder_id,
        "home_slot_id": asset.get("home_slot_id"),
        "current_slot": current_slot,
    }
    return view, errors


def _resolve_replacement_target_slot(
    conn: sqlite3.Connection,
    *,
    failed_asset_id: int,
    failed_asset_tag: str,
    failed_home_slot_id: Optional[int],
) -> tuple[int, dict]:
    occupancy_slot = conn.execute(
        """
        SELECT s.id, s.case_name, s.slot_position, s.current_asset_tag
        FROM slot_occupancy so
        JOIN slots s ON s.id = so.slot_id
        WHERE so.asset_id = ?
        LIMIT 1;
        """,
        (failed_asset_id,),
    ).fetchone()
    if occupancy_slot:
        return int(occupancy_slot["id"]), dict(occupancy_slot)

    if failed_home_slot_id is None:
        raise ValueError("Asset has no slot. Assign a slot first.")

    home_slot = conn.execute(
        """
        SELECT id, case_name, slot_position, current_asset_tag
        FROM slots
        WHERE id = ?
        LIMIT 1;
        """,
        (failed_home_slot_id,),
    ).fetchone()
    if not home_slot:
        raise ValueError("Target slot does not exist.")

    return int(home_slot["id"]), dict(home_slot)


def _validate_swap_target_slot_integrity(
    conn: sqlite3.Connection,
    *,
    target_slot_id: int,
    failed_asset_id: int,
    failed_asset_tag: str,
) -> None:
    occupied = conn.execute(
        """
        SELECT asset_id
        FROM slot_occupancy
        WHERE slot_id = ?
        LIMIT 1;
        """,
        (target_slot_id,),
    ).fetchone()
    if occupied and int(occupied["asset_id"]) != failed_asset_id:
        raise ValueError("Target slot is occupied by another asset.")

    slot_row = conn.execute(
        """
        SELECT current_asset_tag
        FROM slots
        WHERE id = ?
        LIMIT 1;
        """,
        (target_slot_id,),
    ).fetchone()
    if not slot_row:
        raise ValueError("Target slot does not exist.")

    marker = str(slot_row["current_asset_tag"] or "").strip()
    if marker:
        is_failed_asset_marker = marker.upper() == failed_asset_tag.upper() or marker.upper() == failed_asset_tag.upper().replace("-", "")
        if not is_failed_asset_marker:
            raise ValueError("Target slot is occupied by another asset.")


def _build_admin_replace_asset_view(conn, scan_tag: str) -> tuple[Optional[dict], list[str]]:
    asset = _find_asset_for_scan_tag(conn, scan_tag)
    if not asset:
        return None, ["asset_tag not found"]

    location_type = _normalize_location_type(asset.get("location_type"))
    errors: list[str] = []
    if _is_terminal_location_type(location_type):
        errors.append("Asset is already retired/disposed.")
    if location_type not in {"STORAGE", "IN_CUSTODY"}:
        errors.append("Asset must be in STORAGE or IN_CUSTODY to replace.")

    holder_label = "None"
    holder_id = asset.get("current_holder_id")
    if holder_id is not None:
        holder = conn.execute(
            """
            SELECT id, name, identifier
            FROM holders
            WHERE id = ?;
            """,
            (holder_id,),
        ).fetchone()
        if holder:
            identifier = str(holder["identifier"] or "").strip()
            holder_label = f"{holder['name']} ({identifier})" if identifier else str(holder["name"])
        else:
            holder_label = f"ID {holder_id}"

    target_slot_id = None
    target_slot = None
    try:
        target_slot_id, target_slot = _resolve_replacement_target_slot(
            conn,
            failed_asset_id=int(asset["id"]),
            failed_asset_tag=str(asset["asset_tag"]),
            failed_home_slot_id=asset.get("home_slot_id"),
        )
    except ValueError as e:
        errors.append(str(e))

    view = {
        "id": int(asset["id"]),
        "asset_tag": str(asset.get("asset_tag") or ""),
        "location_type": location_type,
        "serial_number": str(asset.get("serial_number") or ""),
        "manufacturer": str(asset.get("manufacturer") or ""),
        "model": str(asset.get("model") or ""),
        "building_room": str(asset.get("building_room") or ""),
        "current_holder": holder_label,
        "current_holder_id": holder_id,
        "home_slot_id": asset.get("home_slot_id"),
        "target_slot_id": target_slot_id,
        "target_slot": target_slot,
    }
    return view, errors


def _build_admin_force_vacate_view(conn, slot_id: int) -> Optional[dict]:
    slot_row = conn.execute(
        """
        SELECT id, case_name, slot_position, current_asset_tag
        FROM slots
        WHERE id = ?;
        """,
        (slot_id,),
    ).fetchone()
    if not slot_row:
        return None

    occupancy_row = conn.execute(
        """
        SELECT
            so.asset_id,
            a.asset_tag,
            a.manufacturer,
            a.model,
            a.serial_number,
            a.location_type,
            a.home_slot_id,
            a.building_room
        FROM slot_occupancy so
        JOIN assets a ON a.id = so.asset_id
        WHERE so.slot_id = ?
        LIMIT 1;
        """,
        (slot_id,),
    ).fetchone()

    occupied = occupancy_row is not None
    asset_view: Optional[dict] = None
    if occupancy_row:
        asset_view = {
            "asset_id": int(occupancy_row["asset_id"]),
            "asset_tag": str(occupancy_row["asset_tag"] or ""),
            "manufacturer": str(occupancy_row["manufacturer"] or ""),
            "model": str(occupancy_row["model"] or ""),
            "serial": str(occupancy_row["serial_number"] or ""),
            "location_type": str(occupancy_row["location_type"] or ""),
            "home_slot_id": occupancy_row["home_slot_id"],
            "building_room": str(occupancy_row["building_room"] or ""),
        }
    else:
        legacy_asset_tag = str(slot_row["current_asset_tag"] or "").strip()
        if legacy_asset_tag:
            occupied = True
            legacy_asset = _find_asset_for_scan_tag(conn, legacy_asset_tag)
            if legacy_asset:
                asset_view = {
                    "asset_id": int(legacy_asset["id"]),
                    "asset_tag": str(legacy_asset.get("asset_tag") or legacy_asset_tag),
                    "manufacturer": str(legacy_asset.get("manufacturer") or ""),
                    "model": str(legacy_asset.get("model") or ""),
                    "serial": str(legacy_asset.get("serial_number") or ""),
                    "location_type": str(legacy_asset.get("location_type") or ""),
                    "home_slot_id": legacy_asset.get("home_slot_id"),
                    "building_room": str(legacy_asset.get("building_room") or ""),
                }
            else:
                asset_view = {
                    "asset_id": None,
                    "asset_tag": legacy_asset_tag,
                    "manufacturer": "",
                    "model": "",
                    "serial": "",
                    "location_type": "",
                    "home_slot_id": None,
                    "building_room": "",
                }

    return {
        "slot_id": int(slot_row["id"]),
        "case_name": str(slot_row["case_name"] or ""),
        "slot_position": int(slot_row["slot_position"]),
        "occupied": occupied,
        "current_asset_tag": str(slot_row["current_asset_tag"] or ""),
        "asset": asset_view,
    }


def _is_truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _require_admin_for_route():
    user = current_user()
    role = str((user or {}).get("role") or "").strip().lower()
    if role != "admin":
        return {"ok": False, "error": "Forbidden"}, 403
    return None


def _require_admin_for_api():
    return _require_admin_for_route()


def _create_admin_asset_in_tx(
    conn: sqlite3.Connection,
    *,
    asset_tag: str,
    actor: str,
    equipment_type: str,
    serial_number: str,
    manufacturer: str,
    building: str,
    room: str,
    model: Optional[str],
    model_code: Optional[str],
    notes: Optional[str],
    assign_case_number: Optional[str],
    assign_slot_number: Optional[int],
) -> dict:
    existing_asset = conn.execute(
        """
        SELECT 1
        FROM assets
        WHERE UPPER(asset_tag) = UPPER(?)
        LIMIT 1;
        """,
        (asset_tag,),
    ).fetchone()
    if existing_asset:
        raise ValueError("asset_tag already exists.")

    existing_serial = conn.execute(
        """
        SELECT 1
        FROM assets
        WHERE TRIM(COALESCE(serial_number, '')) <> ''
          AND UPPER(serial_number) = UPPER(?)
        LIMIT 1;
        """,
        (serial_number,),
    ).fetchone()
    if existing_serial:
        raise ValueError("serial_number already exists.")

    slot_row = None
    if assign_case_number is not None and assign_slot_number is not None:
        slot_row = conn.execute(
            """
            SELECT id, case_name, slot_position, current_asset_tag
            FROM slots
            WHERE UPPER(case_name) = UPPER(?)
              AND slot_position = ?
            LIMIT 1;
            """,
            (assign_case_number, assign_slot_number),
        ).fetchone()
        if slot_row is None:
            raise ValueError("Slot not found for case_number + slot_number.")

        occupied_row = conn.execute(
            """
            SELECT 1
            FROM slot_occupancy
            WHERE slot_id = ?
            LIMIT 1;
            """,
            (int(slot_row["id"]),),
        ).fetchone()
        if occupied_row:
            raise ValueError("Selected slot is already occupied.")

        if str(slot_row["current_asset_tag"] or "").strip():
            raise ValueError("Selected slot is already occupied.")

    now_iso = datetime.now(timezone.utc).isoformat()
    created_date = now_iso.split("T", 1)[0]
    building_room = f"{building}/{room}"

    home_slot_id = int(slot_row["id"]) if slot_row else None
    asset_columns = get_asset_table_columns(conn)
    insert_values: dict[str, object] = {"asset_tag": asset_tag}

    if "equipment_type" in asset_columns:
        insert_values["equipment_type"] = equipment_type
    if "serial_number" in asset_columns:
        insert_values["serial_number"] = serial_number
    if "manufacturer" in asset_columns:
        insert_values["manufacturer"] = manufacturer
    if "building" in asset_columns:
        insert_values["building"] = building
    if "room" in asset_columns:
        insert_values["room"] = room
    if "building_room" in asset_columns:
        insert_values["building_room"] = building_room
    if "model" in asset_columns:
        insert_values["model"] = model
    if "model_code" in asset_columns:
        insert_values["model_code"] = model_code
    if "notes" in asset_columns:
        insert_values["notes"] = notes
    if "case_number" in asset_columns and slot_row:
        insert_values["case_number"] = str(slot_row["case_name"])
    if "slot_number" in asset_columns and slot_row:
        insert_values["slot_number"] = str(slot_row["slot_position"])
    if "custody_state" in asset_columns:
        insert_values["custody_state"] = "in_stock"
    if "accountability_status" in asset_columns:
        insert_values["accountability_status"] = "accountable"
    if "condition" in asset_columns:
        insert_values["condition"] = "serviceable"
    if "retired" in asset_columns:
        insert_values["retired"] = 0
    if "created_date" in asset_columns:
        insert_values["created_date"] = created_date
    if "updated_date" in asset_columns:
        insert_values["updated_date"] = now_iso
    if "location_type" in asset_columns:
        insert_values["location_type"] = "STORAGE"
    if "current_holder_id" in asset_columns:
        insert_values["current_holder_id"] = None
    if "home_slot_id" in asset_columns:
        insert_values["home_slot_id"] = home_slot_id

    column_names = list(insert_values.keys())
    placeholders = ", ".join("?" for _ in column_names)
    cursor = conn.execute(
        f"INSERT INTO assets ({', '.join(column_names)}) VALUES ({placeholders});",
        tuple(insert_values[col] for col in column_names),
    )
    asset_id = int(cursor.lastrowid)

    if slot_row:
        conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (?, ?, ?);
            """,
            (home_slot_id, asset_id, now_iso),
        )
        conn.execute(
            """
            UPDATE slots
            SET current_asset_tag = ?
            WHERE id = ?;
            """,
            (asset_tag, home_slot_id),
        )

    created_payload: dict[str, object] = {}
    if equipment_type:
        created_payload["equipment_type"] = equipment_type
    if serial_number:
        created_payload["serial_number"] = serial_number
    if manufacturer:
        created_payload["manufacturer"] = manufacturer
    if building:
        created_payload["building"] = building
    if room:
        created_payload["room"] = room
    if model:
        created_payload["model"] = model
    if model_code:
        created_payload["model_code"] = model_code

    conn.execute(
        """
        INSERT INTO asset_events (
            asset_tag,
            event_type,
            event_date,
            actor,
            notes,
            payload,
            holder_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (
            asset_tag,
            "ASSET_CREATED",
            now_iso,
            actor,
            notes,
            json.dumps(created_payload) if created_payload else None,
            None,
        ),
    )

    if slot_row:
        slot_payload = {
            "slot_id": home_slot_id,
            "case_number": str(slot_row["case_name"]),
            "slot_number": int(slot_row["slot_position"]),
            "building": building,
            "room": room,
            "equipment_type": equipment_type,
        }
        conn.execute(
            """
            INSERT INTO asset_events (
                asset_tag,
                event_type,
                event_date,
                actor,
                notes,
                payload,
                holder_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                asset_tag,
                "SLOT_ASSIGN",
                now_iso,
                actor,
                notes,
                json.dumps(slot_payload),
                None,
            ),
        )

    return {
        "asset_id": asset_id,
        "asset_tag": asset_tag,
        "home_slot_id": home_slot_id,
        "location_type": "STORAGE",
        "current_holder_id": None,
    }


def _update_admin_asset_in_tx(
    conn: sqlite3.Connection,
    *,
    asset_id: int,
    actor: str,
    serial_number: str,
    manufacturer: str,
    equipment_type: str,
    building: str,
    room: str,
    model: Optional[str],
    model_code: Optional[str],
    notes: Optional[str],
    selected_slot: Optional[dict],
) -> dict:
    locked = conn.execute(
        """
        SELECT *
        FROM assets
        WHERE id = ?
        LIMIT 1;
        """,
        (asset_id,),
    ).fetchone()
    if not locked:
        raise ValueError("asset not found.")

    asset = dict(locked)
    asset_tag = str(asset.get("asset_tag") or "")
    location_type = _normalize_location_type(asset.get("location_type"))
    if _is_terminal_location_type(location_type):
        raise ValueError("Asset is retired/disposed and cannot be edited.")

    if serial_number:
        duplicate_serial = conn.execute(
            """
            SELECT id
            FROM assets
            WHERE id <> ?
              AND TRIM(COALESCE(serial_number, '')) <> ''
              AND UPPER(serial_number) = UPPER(?)
            LIMIT 1;
            """,
            (asset_id, serial_number),
        ).fetchone()
        if duplicate_serial:
            raise ValueError("serial_number already exists.")

    current_slot = _asset_current_slot(conn, asset_id, asset_tag)
    current_slot_id = None if current_slot is None else int(current_slot["slot_id"])
    target_slot_id = None if selected_slot is None else int(selected_slot["id"])

    if target_slot_id is None and asset.get("home_slot_id") is not None:
        raise ValueError("Clearing an existing home slot is not supported here.")

    if current_slot is not None and location_type != "STORAGE":
        raise ValueError("Asset slot occupancy is inconsistent with its location_type.")

    if selected_slot is not None:
        occupied_row = conn.execute(
            """
            SELECT asset_id
            FROM slot_occupancy
            WHERE slot_id = ?
            LIMIT 1;
            """,
            (target_slot_id,),
        ).fetchone()
        if occupied_row and int(occupied_row["asset_id"]) != asset_id:
            raise ValueError("Selected slot is already occupied.")

        legacy_occupied = str(selected_slot.get("current_asset_tag") or "").strip()
        if legacy_occupied and legacy_occupied.upper() != asset_tag.upper():
            raise ValueError("Selected slot is already occupied.")

    now_iso = datetime.now(timezone.utc).isoformat()
    building_room = f"{building}/{room}"
    asset_columns = get_asset_table_columns(conn)

    changed_fields: dict[str, object] = {}
    field_values = {
        "serial_number": serial_number,
        "manufacturer": manufacturer,
        "equipment_type": equipment_type,
        "building": building,
        "room": room,
        "building_room": building_room,
        "model": model,
        "model_code": model_code,
        "notes": notes,
    }
    for key, value in field_values.items():
        if key in asset_columns and asset.get(key) != value:
            changed_fields[key] = value

    if "home_slot_id" in asset_columns and asset.get("home_slot_id") != target_slot_id:
        changed_fields["home_slot_id"] = target_slot_id
    if "case_number" in asset_columns:
        next_case_number = None if selected_slot is None else str(selected_slot["case_name"])
        if asset.get("case_number") != next_case_number:
            changed_fields["case_number"] = next_case_number
    if "slot_number" in asset_columns:
        next_slot_number = None if selected_slot is None else str(selected_slot["slot_position"])
        if asset.get("slot_number") != next_slot_number:
            changed_fields["slot_number"] = next_slot_number

    if location_type == "STORAGE" and current_slot_id != target_slot_id:
        if current_slot_id is not None:
            conn.execute("DELETE FROM slot_occupancy WHERE asset_id = ?;", (asset_id,))
            conn.execute("UPDATE slots SET current_asset_tag = NULL WHERE id = ?;", (current_slot_id,))
        if target_slot_id is not None:
            conn.execute(
                """
                INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
                VALUES (?, ?, ?);
                """,
                (target_slot_id, asset_id, now_iso),
            )
            conn.execute(
                """
                UPDATE slots
                SET current_asset_tag = ?
                WHERE id = ?;
                """,
                (asset_tag, target_slot_id),
            )
    elif location_type not in {"STORAGE", "IN_CUSTODY", ""}:
        raise ValueError("Asset location_type is not supported for admin edit.")

    update_clauses: list[str] = []
    update_values: list[object] = []
    for key, value in changed_fields.items():
        update_clauses.append(f"{key} = ?")
        update_values.append(value)
    if "updated_date" in asset_columns:
        update_clauses.append("updated_date = ?")
        update_values.append(now_iso)
    if update_clauses:
        update_values.append(asset_id)
        conn.execute(
            f"UPDATE assets SET {', '.join(update_clauses)} WHERE id = ?;",
            tuple(update_values),
        )

    if current_slot_id != target_slot_id:
        if location_type == "STORAGE" and current_slot_id is None and selected_slot is not None:
            payload = {
                "slot_id": target_slot_id,
                "case_number": str(selected_slot["case_name"]),
                "slot_number": int(selected_slot["slot_position"]),
                "building": building,
                "room": room,
                "equipment_type": equipment_type,
            }
            conn.execute(
                """
                INSERT INTO asset_events (
                    asset_tag,
                    event_type,
                    event_date,
                    actor,
                    notes,
                    payload,
                    holder_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (asset_tag, "SLOT_ASSIGN", now_iso, actor, notes, json.dumps(payload), None),
            )
        else:
            payload = {
                "from_slot_id": current_slot_id,
                "to_slot_id": target_slot_id,
                "case_number": None if selected_slot is None else str(selected_slot["case_name"]),
                "slot_number": None if selected_slot is None else int(selected_slot["slot_position"]),
                "location_type": location_type,
            }
            conn.execute(
                """
                INSERT INTO asset_events (
                    asset_tag,
                    event_type,
                    event_date,
                    actor,
                    notes,
                    payload,
                    holder_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (asset_tag, "ASSET_UPDATED", now_iso, actor, notes, json.dumps(payload), asset.get("current_holder_id")),
            )

    metadata_payload = dict(changed_fields)
    if metadata_payload:
        metadata_payload["asset_id"] = asset_id
        conn.execute(
            """
            INSERT INTO asset_events (
                asset_tag,
                event_type,
                event_date,
                actor,
                notes,
                payload,
                holder_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                asset_tag,
                "ASSET_UPDATED",
                now_iso,
                actor,
                notes,
                json.dumps(metadata_payload),
                asset.get("current_holder_id"),
            ),
        )

    return {
        "asset_id": asset_id,
        "asset_tag": asset_tag,
        "location_type": location_type,
        "home_slot_id": target_slot_id,
        "current_holder_id": asset.get("current_holder_id"),
    }


def _retire_admin_asset_in_tx(
    conn: sqlite3.Connection,
    *,
    asset_id: int,
    asset_tag: str,
    failure_type: str,
    notes: str,
    actor: str,
) -> dict:
    locked_row = conn.execute(
        """
        SELECT id, asset_tag, location_type, current_holder_id, home_slot_id
        FROM assets
        WHERE id = ?
        LIMIT 1;
        """,
        (asset_id,),
    ).fetchone()
    if not locked_row:
        raise ValueError("asset_tag not found")

    origin_location = _normalize_location_type(locked_row["location_type"])
    if _is_terminal_location_type(origin_location):
        raise ValueError("Asset is already retired/disposed.")
    if origin_location not in {"STORAGE", "IN_CUSTODY"}:
        raise ValueError("Asset must be in STORAGE or IN_CUSTODY to retire.")

    now_iso = datetime.now(timezone.utc).isoformat()
    event_type = "ASSET_RETIRED_IN_FIELD" if origin_location == "IN_CUSTODY" else "ASSET_RETIRED"

    occupied_slots = conn.execute(
        """
        SELECT slot_id
        FROM slot_occupancy
        WHERE asset_id = ?;
        """,
        (asset_id,),
    ).fetchall()
    cleared_slot_ids = [int(row["slot_id"]) for row in occupied_slots]

    conn.execute(
        """
        DELETE FROM slot_occupancy
        WHERE asset_id = ?;
        """,
        (asset_id,),
    )
    conn.execute(
        """
        UPDATE slots
        SET current_asset_tag = NULL
        WHERE UPPER(current_asset_tag) = UPPER(?)
           OR REPLACE(UPPER(current_asset_tag), '-', '') = UPPER(?);
        """,
        (asset_tag, asset_tag),
    )

    asset_columns = get_asset_table_columns(conn)
    update_clauses = [
        "location_type = ?",
        "current_holder_id = NULL",
        "home_slot_id = NULL",
    ]
    update_values: list[object] = [TERMINAL_LOCATION_TYPE]
    if "updated_date" in asset_columns:
        update_clauses.append("updated_date = ?")
        update_values.append(now_iso)

    update_values.append(asset_id)
    conn.execute(
        f"UPDATE assets SET {', '.join(update_clauses)} WHERE id = ?;",
        tuple(update_values),
    )

    payload = {
        "failure_type": failure_type,
        "notes": notes,
        "from_location_type": origin_location,
        "to_location_type": TERMINAL_LOCATION_TYPE,
        "cleared_slot_ids": cleared_slot_ids,
        "previous_holder_id": locked_row["current_holder_id"],
        "previous_home_slot_id": locked_row["home_slot_id"],
    }
    conn.execute(
        """
        INSERT INTO asset_events (
            asset_tag,
            event_type,
            event_date,
            actor,
            notes,
            payload,
            holder_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (
            str(locked_row["asset_tag"]),
            event_type,
            now_iso,
            actor,
            notes,
            json.dumps(payload),
            locked_row["current_holder_id"],
        ),
    )

    return {
        "asset_tag": str(locked_row["asset_tag"]),
        "event_type": event_type,
        "from_location_type": origin_location,
        "to_location_type": TERMINAL_LOCATION_TYPE,
    }


def _selected_holder_from_session() -> Optional[dict]:
    holder_id = session.get("holder_id")
    if holder_id is None:
        return None

    holder = get_holder(holder_id)
    if holder is None:
        session.pop("holder_id", None)
    return holder


def _issue_location_form_from_session() -> dict[str, str]:
    return {
        "building": str(session.get("issue_building") or "").strip(),
        "room": str(session.get("issue_room") or "").strip(),
    }


def _issue_location_context(selected_holder: Optional[dict], form: Optional[dict[str, str]] = None) -> dict:
    normalized_form = {
        "building": str((form or {}).get("building") or "").strip(),
        "room": str((form or {}).get("room") or "").strip(),
    }
    all_building_names = [str(row.get("name") or "").strip() for row in list_buildings()]
    all_building_names = [name for name in all_building_names if name]
    allowed_building_names = list(all_building_names)
    constrained_by_org = False

    holder_org_id = None if not selected_holder else selected_holder.get("organization_id")
    try:
        normalized_holder_org_id = None if holder_org_id in {None, ""} else int(holder_org_id)
    except (TypeError, ValueError):
        normalized_holder_org_id = None

    if normalized_holder_org_id is not None:
        mapped_buildings = [
            str(mapping.get("building_name") or "").strip()
            for mapping in list_organization_building_mappings()
            if int(mapping["organization_id"]) == normalized_holder_org_id
        ]
        mapped_buildings = [name for name in mapped_buildings if name]
        if mapped_buildings:
            constrained_by_org = True
            allowed_building_names = mapped_buildings

    return {
        "form": normalized_form,
        "building_options": allowed_building_names,
        "has_reference_buildings": bool(all_building_names),
        "constrained_by_org": constrained_by_org,
    }


def _validate_issue_location_form(selected_holder: Optional[dict], form: dict[str, str]) -> tuple[dict[str, str], list[str], dict]:
    context = _issue_location_context(selected_holder, form)
    normalized_form = context["form"]
    errors: list[str] = []

    if selected_holder is None:
        errors.append("Select a holder before choosing the current location.")
        return normalized_form, errors, context

    building = normalized_form["building"]
    room = normalized_form["room"]
    building_options = list(context["building_options"])
    building_name_map = {name.upper(): name for name in building_options}

    if not building:
        errors.append("Choose the current building.")
    elif building_name_map:
        matched_name = building_name_map.get(building.upper())
        if matched_name is None:
            if context["constrained_by_org"]:
                errors.append("Choose a building allowed for the selected organization.")
            else:
                errors.append("Choose a valid building.")
        else:
            normalized_form["building"] = matched_name

    if not room:
        errors.append("Enter the current room or area.")

    return normalized_form, errors, context


def _issue_location_label(form: dict[str, str]) -> str:
    building = str(form.get("building") or "").strip()
    room = str(form.get("room") or "").strip()
    if building and room:
        return f"{building} / {room}"
    if building:
        return building
    return ""


def _queue_asset_tags() -> list[str]:
    tags: list[str] = []
    for s in SCAN_QUEUE:
        tag = (s.asset_tag or "").strip()
        if tag:
            tags.append(tag)
    return tags


def _build_issue_preview_state(asset_tags: list[str], selected_holder: Optional[dict]) -> dict:
    holder_label = None
    if selected_holder:
        identifier = (selected_holder.get("identifier") or "").strip()
        display_name = _holder_display_name(selected_holder)
        holder_label = display_name if not identifier else f"{display_name} ({identifier})"
    issue_location_form, issue_location_errors, _ = _validate_issue_location_form(
        selected_holder,
        _issue_location_form_from_session(),
    )
    issue_location_label = _issue_location_label(issue_location_form)

    assets: list[dict] = []
    unknown_tags: list[str] = []
    not_storage: list[str] = []
    retired_assets: list[str] = []
    not_slotted: list[str] = []
    blocking_issues: list[str] = []

    if not asset_tags:
        blocking_issues.append("Queue is empty. Scan assets before committing.")
        return {
            "assets": assets,
            "ready_count": 0,
            "blocking_issues": blocking_issues,
            "holder_label": holder_label,
        }

    if selected_holder is None:
        blocking_issues.append("No holder selected. Select a holder before issuing assets.")
    for error in issue_location_errors:
        blocking_issues.append(error)

    def _canon_asset_row_for_scan_tag(conn, scan_tag: str) -> Optional[dict]:
        t = (scan_tag or "").strip()
        if not t:
            return None

        rows = conn.execute(
            """
            SELECT id, asset_tag, location_type, current_holder_id, building_room, home_slot_id
            FROM assets
            WHERE UPPER(asset_tag) = UPPER(?)
               OR REPLACE(UPPER(asset_tag), '-', '') = UPPER(?)
            LIMIT 2;
            """,
            (t, t),
        ).fetchall()

        if not rows:
            return None

        if len(rows) > 1 and str(rows[0]["asset_tag"]) != str(rows[1]["asset_tag"]):
            raise ValueError(f"Ambiguous asset_tag match for scan '{t}'")

        return dict(rows[0])

    conn = get_connection()
    try:
        asset_columns = get_asset_table_columns(conn)
        required_columns = {"location_type", "current_holder_id", "building_room"}
        missing_columns = sorted(required_columns - asset_columns)
        if missing_columns:
            blocking_issues.append(f"Assets table missing columns: {', '.join(missing_columns)}")
            return {
                "assets": assets,
                "ready_count": 0,
                "blocking_issues": blocking_issues,
                "holder_label": holder_label,
            }

        for scan_tag in asset_tags:
            row: dict = {
                "scanned_tag": scan_tag,
                "asset_tag": scan_tag,
                "canonical_tag": None,
                "before_location_type": "UNKNOWN",
                "after_location_type": "IN_CUSTODY",
                "before_current_location": "null",
                "after_current_location": issue_location_label or "(choose current location)",
                "before_holder": "null",
                "after_holder": holder_label or "(select holder)",
                "before_home_location": "null",
                "after_home_location": "null",
                "before_slot_occupancy": "unknown",
                "after_slot_occupancy": "vacated",
                "ready": False,
                "asset_issues": [],
            }

            asset_row = _canon_asset_row_for_scan_tag(conn, scan_tag)
            if not asset_row:
                row["asset_issues"].append("Unknown asset tag")
                unknown_tags.append(scan_tag)
                assets.append(row)
                continue

            canon_tag = str(asset_row["asset_tag"])
            row["asset_tag"] = canon_tag
            row["canonical_tag"] = canon_tag

            before_location = str(asset_row["location_type"] or "").strip().upper()
            row["before_location_type"] = before_location or "UNKNOWN"
            row["before_current_location"] = str(asset_row["building_room"] or "").strip() or "null"
            if _is_terminal_location_type(before_location):
                row["asset_issues"].append("Asset is retired/disposed")
                retired_assets.append(canon_tag)

            before_holder_id = asset_row["current_holder_id"]
            row["before_holder"] = "null" if before_holder_id is None else str(before_holder_id)

            current_slot = _asset_current_slot(conn, int(asset_row["id"]), canon_tag)
            slotted = current_slot is not None
            home_slot_id = asset_row.get("home_slot_id")
            if home_slot_id is not None:
                home_slot = conn.execute(
                    """
                    SELECT case_name, slot_position
                    FROM slots
                    WHERE id = ?;
                    """,
                    (int(home_slot_id),),
                ).fetchone()
                if home_slot is not None:
                    row["before_home_location"] = f"{home_slot['case_name']} / {home_slot['slot_position']}"
            row["before_slot_occupancy"] = "occupied" if slotted else "vacant"
            row["after_home_location"] = row["before_home_location"]

            if before_location != "STORAGE":
                row["asset_issues"].append("Asset is not in STORAGE")
                not_storage.append(canon_tag)

            if not slotted:
                row["asset_issues"].append("Asset is not currently slotted")
                not_slotted.append(canon_tag)

            row["ready"] = bool(selected_holder is not None and not row["asset_issues"])
            assets.append(row)
    finally:
        conn.close()

    if unknown_tags:
        blocking_issues.append(f"Unknown asset_tag(s): {', '.join(unknown_tags)}")
    if not_storage:
        blocking_issues.append(f"Not in STORAGE: {', '.join(not_storage)}")
    if retired_assets:
        blocking_issues.append(f"Retired/disposed: {', '.join(retired_assets)}")
    if not_slotted:
        blocking_issues.append(f"Not currently slotted: {', '.join(not_slotted)}")

    ready_count = sum(1 for row in assets if row["ready"])
    return {
        "assets": assets,
        "ready_count": ready_count,
        "blocking_issues": blocking_issues,
        "holder_label": holder_label,
    }


def _build_return_preview_state(asset_tags: list[str]) -> dict:
    assets: list[dict] = []
    unknown_tags: list[str] = []
    not_in_custody: list[str] = []
    retired_assets: list[str] = []
    no_home_slot: list[str] = []
    occupied_home_slot: list[str] = []
    blocking_issues: list[str] = []

    if not asset_tags:
        blocking_issues.append("Queue is empty. Scan assets before returning.")
        return {"assets": assets, "ready_count": 0, "blocking_issues": blocking_issues}

    def _canon_asset_row_for_scan_tag(conn, scan_tag: str) -> Optional[dict]:
        t = (scan_tag or "").strip()
        if not t:
            return None

        rows = conn.execute(
            """
            SELECT asset_tag, location_type, current_holder_id, home_slot_id
            FROM assets
            WHERE UPPER(asset_tag) = UPPER(?)
               OR REPLACE(UPPER(asset_tag), '-', '') = UPPER(?)
            LIMIT 2;
            """,
            (t, t),
        ).fetchall()

        if not rows:
            return None

        if len(rows) > 1 and str(rows[0]["asset_tag"]) != str(rows[1]["asset_tag"]):
            raise ValueError(f"Ambiguous asset_tag match for scan '{t}'")

        return dict(rows[0])

    conn = get_connection()
    try:
        asset_columns = get_asset_table_columns(conn)
        required_columns = {"location_type", "current_holder_id", "home_slot_id"}
        missing_columns = sorted(required_columns - asset_columns)
        if missing_columns:
            blocking_issues.append(f"Assets table missing columns: {', '.join(missing_columns)}")
            return {"assets": assets, "ready_count": 0, "blocking_issues": blocking_issues}

        for scan_tag in asset_tags:
            row: dict = {
                "scanned_tag": scan_tag,
                "canonical_tag": None,
                "before_location_type": "UNKNOWN",
                "after_location_type": "STORAGE",
                "before_holder": "null",
                "after_holder": "null",
                "destination_slot": "unknown",
                "destination_case_name": None,
                "before_slot_occupancy": "empty",
                "after_slot_occupancy": "occupied",
                "ready": False,
                "asset_issues": [],
            }

            asset_row = _canon_asset_row_for_scan_tag(conn, scan_tag)
            if not asset_row:
                row["asset_issues"].append("Unknown asset tag")
                unknown_tags.append(scan_tag)
                assets.append(row)
                continue

            canon_tag = str(asset_row["asset_tag"])
            row["canonical_tag"] = canon_tag

            location_type = str(asset_row["location_type"] or "").strip().upper()
            row["before_location_type"] = location_type or "UNKNOWN"
            if _is_terminal_location_type(location_type):
                row["asset_issues"].append("Asset is retired/disposed")
                retired_assets.append(canon_tag)
            if location_type != "IN_CUSTODY":
                row["asset_issues"].append("Asset is not in IN_CUSTODY")
                not_in_custody.append(canon_tag)

            current_holder_id = asset_row["current_holder_id"]
            if current_holder_id is not None:
                holder = get_holder(current_holder_id)
                row["before_holder"] = (
                    holder["name"] if holder is not None else f"holder_id {current_holder_id}"
                )

            home_slot_id = asset_row["home_slot_id"]
            if home_slot_id is None:
                row["asset_issues"].append("Asset has no home slot")
                no_home_slot.append(canon_tag)
                assets.append(row)
                continue

            slot = conn.execute(
                """
                SELECT id, case_name, slot_position, current_asset_tag
                FROM slots
                WHERE id = ?;
                """,
                (home_slot_id,),
            ).fetchone()
            if not slot:
                row["asset_issues"].append("Home slot not found")
                no_home_slot.append(canon_tag)
                assets.append(row)
                continue

            row["destination_case_name"] = str(slot["case_name"])
            row["destination_slot"] = f"{slot['case_name']} / {slot['slot_position']}"
            if slot["current_asset_tag"] is not None:
                row["asset_issues"].append(f"Home slot occupied by {slot['current_asset_tag']}")
                occupied_home_slot.append(canon_tag)
                row["before_slot_occupancy"] = "occupied"

            row["ready"] = not row["asset_issues"]
            assets.append(row)
    finally:
        conn.close()

    if unknown_tags:
        blocking_issues.append(f"Unknown asset_tag(s): {', '.join(unknown_tags)}")
    if not_in_custody:
        blocking_issues.append(f"Not in IN_CUSTODY: {', '.join(not_in_custody)}")
    if retired_assets:
        blocking_issues.append(f"Retired/disposed: {', '.join(retired_assets)}")
    if no_home_slot:
        blocking_issues.append(f"Missing home slot: {', '.join(no_home_slot)}")
    if occupied_home_slot:
        blocking_issues.append(f"Home slot occupied: {', '.join(occupied_home_slot)}")

    ready_count = sum(1 for row in assets if row["ready"])
    return {"assets": assets, "ready_count": ready_count, "blocking_issues": blocking_issues}


def _issue_batch(asset_tags: list[str], holder_id: int, issue_location: dict[str, str]) -> int:
    if not asset_tags:
        raise ValueError("No assets in the queue to issue.")

    def _canon_asset_row_for_scan_tag(conn, scan_tag: str) -> Optional[dict]:
        """
        Accept either:
          - exact tag match
          - match where dashes are removed from DB value (common label format)
        Returns the canonical DB row (including canonical asset_tag).
        Hard-stops if multiple distinct matches.
        """
        t = (scan_tag or "").strip()
        if not t:
            return None

        rows = conn.execute(
            """
            SELECT id, asset_tag, location_type, building_room, home_slot_id
            FROM assets
            WHERE UPPER(asset_tag) = UPPER(?)
               OR REPLACE(UPPER(asset_tag), '-', '') = UPPER(?)
            LIMIT 2;
            """,
            (t, t),
        ).fetchall()

        if not rows:
            return None

        # If we got 2 rows and the canonical tags differ, that's ambiguous.
        if len(rows) > 1 and str(rows[0]["asset_tag"]) != str(rows[1]["asset_tag"]):
            raise ValueError(f"Ambiguous asset_tag match for scan '{t}'")

        return dict(rows[0])

    conn = get_connection()
    try:
        with conn:
            asset_columns = get_asset_table_columns(conn)
            required_columns = {"location_type", "current_holder_id", "building_room"}
            missing_columns = sorted(required_columns - asset_columns)
            if missing_columns:
                raise ValueError(f"Assets table missing columns: {', '.join(missing_columns)}")

            building = str(issue_location.get("building") or "").strip()
            room = str(issue_location.get("room") or "").strip()
            building_room = f"{building}/{room}"

            unknown_tags: list[str] = []
            not_storage: list[str] = []
            retired_assets: list[str] = []
            not_slotted: list[str] = []

            # Map scan tags -> canonical DB rows (so we update/vacate consistently)
            canon_assets: list[tuple[int, str, Optional[int]]] = []

            for scan_tag in asset_tags:
                asset_row = _canon_asset_row_for_scan_tag(conn, scan_tag)
                if not asset_row:
                    unknown_tags.append(scan_tag)
                    continue

                canon_tag = str(asset_row["asset_tag"])
                asset_id = int(asset_row["id"])
                home_slot_id = None if asset_row.get("home_slot_id") is None else int(asset_row["home_slot_id"])
                canon_assets.append((asset_id, canon_tag, home_slot_id))

                location_type = str(asset_row["location_type"] or "").strip().upper()
                if _is_terminal_location_type(location_type):
                    retired_assets.append(canon_tag)
                if location_type != "STORAGE":
                    not_storage.append(canon_tag)

                if _asset_current_slot(conn, int(asset_row["id"]), canon_tag) is None:
                    not_slotted.append(canon_tag)

            if unknown_tags or not_storage or retired_assets or not_slotted:
                parts: list[str] = []
                if unknown_tags:
                    parts.append(f"Unknown asset_tag(s): {', '.join(unknown_tags)}")
                if not_storage:
                    parts.append(f"Not in STORAGE: {', '.join(not_storage)}")
                if retired_assets:
                    parts.append(f"Retired/disposed: {', '.join(retired_assets)}")
                if not_slotted:
                    parts.append(f"Not currently slotted: {', '.join(not_slotted)}")
                raise ValueError("; ".join(parts))

            now_iso = datetime.now(timezone.utc).isoformat()

            for asset_id, canon_tag, home_slot_id in canon_assets:
                asset_row = conn.execute(
                    """
                    SELECT building_room
                    FROM assets
                    WHERE id = ?
                    LIMIT 1;
                    """,
                    (asset_id,),
                ).fetchone()
                previous_building_room = "" if asset_row is None else str(asset_row["building_room"] or "").strip()

                update_clauses = ["location_type = ?", "current_holder_id = ?"]
                update_values: list[object] = ["IN_CUSTODY", holder_id]
                if "building" in asset_columns:
                    update_clauses.append("building = ?")
                    update_values.append(building)
                if "room" in asset_columns:
                    update_clauses.append("room = ?")
                    update_values.append(room)
                if "building_room" in asset_columns:
                    update_clauses.append("building_room = ?")
                    update_values.append(building_room)
                update_values.extend([canon_tag, canon_tag])

                conn.execute(
                    f"""
                    UPDATE assets
                    SET {', '.join(update_clauses)}
                    WHERE UPPER(asset_tag) = UPPER(?)
                       OR REPLACE(UPPER(asset_tag), '-', '') = UPPER(?);
                    """,
                    tuple(update_values),
                )

                current_slot = _asset_current_slot(conn, asset_id, canon_tag)
                if current_slot is None:
                    raise ValueError(f"Not currently slotted: {canon_tag}")

                conn.execute(
                    """
                    DELETE FROM slot_occupancy
                    WHERE asset_id = ?;
                    """,
                    (asset_id,),
                )
                conn.execute(
                    """
                    UPDATE slots
                    SET current_asset_tag = NULL
                    WHERE id = ?;
                    """,
                    (int(current_slot["slot_id"]),),
                )

                conn.execute(
                    """
                    INSERT INTO asset_events (
                        asset_tag,
                        event_type,
                        event_date,
                        actor,
                        notes,
                    payload,
                    holder_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                    (
                        canon_tag,
                        ISSUE_EVENT_TYPE,
                        now_iso,
                        "system",
                        None,
                        json.dumps(
                            {
                                "from_location_type": "STORAGE",
                                "to_location_type": "IN_CUSTODY",
                                "from_building_room": previous_building_room,
                                "to_building_room": building_room,
                                "home_slot_id": home_slot_id,
                            }
                        ),
                        holder_id,
                    ),
                )

            return len(canon_assets)
    finally:
        conn.close()


def _return_batch(asset_tags: list[str]) -> int:
    if not asset_tags:
        raise ValueError("No assets in the queue to return")

    def _canon_asset_row_for_scan_tag(conn, scan_tag: str) -> Optional[dict]:
        t = (scan_tag or "").strip()
        if not t:
            return None

        rows = conn.execute(
            """
            SELECT asset_tag, location_type, home_slot_id
            FROM assets
            WHERE UPPER(asset_tag) = UPPER(?)
               OR REPLACE(UPPER(asset_tag), '-', '') = UPPER(?)
            LIMIT 2;
            """,
            (t, t),
        ).fetchall()

        if not rows:
            return None

        if len(rows) > 1 and str(rows[0]["asset_tag"]) != str(rows[1]["asset_tag"]):
            raise ValueError(f"Ambiguous asset_tag match for scan '{t}'")

        return dict(rows[0])

    conn = get_connection()
    try:
        with conn:
            asset_columns = get_asset_table_columns(conn)
            required_columns = {"location_type", "current_holder_id", "home_slot_id"}
            missing_columns = sorted(required_columns - asset_columns)
            if missing_columns:
                raise ValueError(f"Assets table missing columns: {', '.join(missing_columns)}")

            unknown_tags: list[str] = []
            not_in_custody: list[str] = []
            retired_assets: list[str] = []
            no_home_slot: list[str] = []
            occupied_home_slot: list[str] = []
            validated_rows: list[dict] = []

            for scan_tag in asset_tags:
                asset_row = _canon_asset_row_for_scan_tag(conn, scan_tag)
                if not asset_row:
                    unknown_tags.append(scan_tag)
                    continue

                canon_tag = str(asset_row["asset_tag"])

                location_type = str(asset_row["location_type"] or "").strip().upper()
                if _is_terminal_location_type(location_type):
                    retired_assets.append(canon_tag)
                if location_type != "IN_CUSTODY":
                    not_in_custody.append(canon_tag)

                home_slot_id = asset_row["home_slot_id"]
                if home_slot_id is None:
                    no_home_slot.append(canon_tag)
                    continue

                slot = conn.execute(
                    """
                    SELECT id, case_name, slot_position, current_asset_tag
                    FROM slots
                    WHERE id = ?;
                    """,
                    (home_slot_id,),
                ).fetchone()
                if not slot:
                    no_home_slot.append(canon_tag)
                    continue

                if slot["current_asset_tag"] is not None:
                    occupied_home_slot.append(canon_tag)

                validated_rows.append({"asset_tag": canon_tag, "home_slot_id": int(slot["id"])})

            if unknown_tags or not_in_custody or retired_assets or no_home_slot or occupied_home_slot:
                parts: list[str] = []
                if unknown_tags:
                    parts.append(f"Unknown asset_tag(s): {', '.join(unknown_tags)}")
                if not_in_custody:
                    parts.append(f"Not in IN_CUSTODY: {', '.join(not_in_custody)}")
                if retired_assets:
                    parts.append(f"Retired/disposed: {', '.join(retired_assets)}")
                if no_home_slot:
                    parts.append(f"Missing home slot: {', '.join(no_home_slot)}")
                if occupied_home_slot:
                    parts.append(f"Home slot occupied: {', '.join(occupied_home_slot)}")
                raise ValueError("; ".join(parts))

            now_iso = datetime.now(timezone.utc).isoformat()

            for row in validated_rows:
                canon_tag = row["asset_tag"]
                home_slot_id = row["home_slot_id"]

                conn.execute(
                    """
                    UPDATE assets
                    SET location_type = ?, current_holder_id = NULL
                    WHERE UPPER(asset_tag) = UPPER(?)
                       OR REPLACE(UPPER(asset_tag), '-', '') = UPPER(?);
                    """,
                    ("STORAGE", canon_tag, canon_tag),
                )

                cursor = conn.execute(
                    """
                    UPDATE slots
                    SET current_asset_tag = ?
                    WHERE id = ? AND current_asset_tag IS NULL;
                    """,
                    (canon_tag, home_slot_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError(f"Home slot became occupied for {canon_tag}")

                conn.execute(
                    """
                    INSERT INTO asset_events (
                        asset_tag,
                        event_type,
                        event_date,
                        actor,
                        notes,
                        payload,
                        holder_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (canon_tag, RETURN_EVENT_TYPE, now_iso, "system", None, None, None),
                )

            return len(validated_rows)
    finally:
        conn.close()

# Routes

@app.route("/", methods=["GET", "POST"])
def intake():
    if request.method == "GET":
        if current_user() is not None:
            return redirect("/dashboard")
        return render_template("splash.html", error=None)

    if current_user() is not None:
        action = (request.form.get("action") or "").strip().lower()
        scan_text = (request.form.get("scan_text") or "").strip()
        return_to = (request.form.get("return_to") or "").strip()
        return_to_path = _return_to_path(return_to)
        redirect_target = _queue_redirect_target(return_to)
        queue_index_raw = (request.form.get("queue_index") or "").strip()
        submitted_equipment_type = request.form.get("equipment_type")
        current_equipment_type = (session.get("equipment_type") or "laptop").strip() or "laptop"
        if submitted_equipment_type is None:
            selected_equipment_type = current_equipment_type
        else:
            selected_equipment_type = (submitted_equipment_type or "").strip() or "laptop"
        session["equipment_type"] = selected_equipment_type

        if action == "clear":
            SCAN_QUEUE.clear()
        elif action == "remove":
            try:
                queue_index = int(queue_index_raw)
            except ValueError:
                queue_index = -1

            if 0 <= queue_index < len(SCAN_QUEUE):
                SCAN_QUEUE.pop(queue_index)

        should_validate_empty_scan = (
            action == ""
            and not scan_text
            and return_to_path in {"", "/add-assets"}
        )
        if should_validate_empty_scan:
            flash("Enter or scan an asset tag before adding it to the queue.", "error")
            touch_session()
            if redirect_target.startswith("/") and not redirect_target.startswith("//"):
                return redirect(redirect_target)
            return redirect(url_for("add_assets"))

        if scan_text:
            if return_to_path == "/issue":
                selected_holder = _selected_holder_from_session()
                issue_location_form, issue_location_errors, _ = _validate_issue_location_form(
                    selected_holder,
                    _issue_location_form_from_session(),
                )
                if selected_holder is None:
                    flash("Select a holder before issuing assets.", "error")
                    touch_session()
                    return redirect(url_for("holders_search", return_to=url_for("issue")))
                if issue_location_errors:
                    flash(
                        f"Scan not added. {issue_location_errors[0]} Set the current location, then scan again.",
                        "error scan-feedback",
                    )
                    touch_session()
                    if redirect_target.startswith("/") and not redirect_target.startswith("//"):
                        return redirect(redirect_target)
                    return redirect(url_for("issue"))
                session["issue_building"] = issue_location_form["building"]
                session["issue_room"] = issue_location_form["room"]

            value = sanitize_scan(scan_text)
            if not value:
                flash("Scan rejected. Enter a valid asset tag.", "error")
                touch_session()
                if redirect_target.startswith("/") and not redirect_target.startswith("//"):
                    return redirect(redirect_target)
                return redirect(url_for("add_assets"))

            case_name = (request.form.get("case_name") or "").strip().upper()
            slot_id_raw = (request.form.get("slot_id") or "").strip()
            home_slot_id: Optional[int] = None
            slot_position: Optional[int] = None
            requires_inventory_validation = return_to_path in {"/issue", "/return"}
            if requires_inventory_validation or case_name or slot_id_raw:
                conn = get_connection()
                try:
                    case_match = None
                    if return_to_path == "/issue":
                        try:
                            case_match = _find_case_assets_for_scan_tag(conn, value)
                        except ValueError as e:
                            flash(str(e), "error")
                            touch_session()
                            if redirect_target.startswith("/") and not redirect_target.startswith("//"):
                                return redirect(redirect_target)
                            return redirect(url_for("add_assets"))

                        if case_match is not None:
                            matched_case_name = str(case_match["case_name"] or value).strip().upper()
                            case_assets = list(case_match["assets"])
                            if not case_assets:
                                flash(f"Case {matched_case_name} has no assets to add.", "error")
                                touch_session()
                                if redirect_target.startswith("/") and not redirect_target.startswith("//"):
                                    return redirect(redirect_target)
                                return redirect(url_for("add_assets"))

                            added_count = 0
                            skipped_count = 0
                            for row in case_assets:
                                asset_tag = str(row["asset_tag"] or "").strip().upper()
                                if _queue_contains_asset_tag(asset_tag):
                                    skipped_count += 1
                                    continue
                                SCAN_QUEUE.append(
                                    Scan.now(
                                        asset_tag,
                                        equipment_type=selected_equipment_type,
                                        home_slot_id=int(row["home_slot_id"]),
                                        case_name=str(row["case_name"] or ""),
                                        slot_position=int(row["slot_position"]),
                                    )
                                )
                                added_count += 1

                            if added_count > 0:
                                message = f"Case {matched_case_name} added {added_count} asset"
                                if added_count != 1:
                                    message += "s"
                                message += " to queue."
                                if skipped_count > 0:
                                    message += f" Skipped {skipped_count} already queued."
                                flash(message, "success")
                            else:
                                flash(f"Case {matched_case_name} is already fully queued.", "error")

                            touch_session()
                            if redirect_target.startswith("/") and not redirect_target.startswith("//"):
                                return redirect(redirect_target)
                            return redirect(url_for("add_assets"))

                    if _queue_contains_asset_tag(value):
                        flash(f"Asset {value} is already queued.", "error")
                        touch_session()
                        if redirect_target.startswith("/") and not redirect_target.startswith("//"):
                            return redirect(redirect_target)
                        return redirect(url_for("add_assets"))

                    if requires_inventory_validation and _find_asset_for_scan_tag(conn, value) is None:
                        flash("Scan rejected. Asset tag not found in inventory.", "error")
                        touch_session()
                        if redirect_target.startswith("/") and not redirect_target.startswith("//"):
                            return redirect(redirect_target)
                        return redirect(url_for("add_assets"))

                    if case_name or slot_id_raw:
                        selected_slot, slot_errors = _resolve_slot_selection(
                            conn,
                            case_name=case_name,
                            slot_id_raw=slot_id_raw,
                        )
                        if slot_errors:
                            flash("; ".join(slot_errors), "error")
                            touch_session()
                            if redirect_target.startswith("/") and not redirect_target.startswith("//"):
                                return redirect(redirect_target)
                            return redirect(url_for("add_assets"))
                        if selected_slot is not None:
                            home_slot_id = int(selected_slot["id"])
                            case_name = str(selected_slot["case_name"])
                            slot_position = int(selected_slot["slot_position"])
                finally:
                    conn.close()
            elif _queue_contains_asset_tag(value):
                flash(f"Asset {value} is already queued.", "error")
                touch_session()
                if redirect_target.startswith("/") and not redirect_target.startswith("//"):
                    return redirect(redirect_target)
                return redirect(url_for("add_assets"))

            SCAN_QUEUE.append(
                Scan.now(
                    value,
                    equipment_type=selected_equipment_type,
                    home_slot_id=home_slot_id,
                    case_name=case_name,
                    slot_position=slot_position,
                )
            )

        touch_session()

        if redirect_target.startswith("/") and not redirect_target.startswith("//"):
            return redirect(redirect_target)
        return redirect(url_for("add_assets"))

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    user = get_user_by_username(username)
    if user is None or not verify_password(user, password):
        return render_template("splash.html", error="Invalid login"), 403

    role = str(user.get("role") or "").strip().lower()
    active = int(user.get("active") or 0) == 1
    if role not in {"admin", "operator"} or not active:
        session.pop("user_id", None)
        return render_template("splash.html", error="Access denied"), 403

    session["user_id"] = int(user["id"])
    touch_session()
    return redirect("/dashboard")


@app.get("/add-assets")
def add_assets():
    if current_user() is None:
        return redirect(url_for("intake"))

    if session.get("last_seen") is None:
        touch_session()

    slot_options: list[dict] = []
    case_options: list[str] = []
    conn = get_connection()
    try:
        slot_options = _list_slot_options(conn)
        case_options = _slot_case_options(slot_options)
    finally:
        conn.close()

    return render_template(
        "index.html",
        auth_enabled=auth_enabled(),
        authed=is_authed(),
        last_seen_age_seconds=seconds_since_last_seen(),
        timeout_seconds=INTAKE_TIMEOUT_SECONDS,
        queue=SCAN_QUEUE,
        queue_len=len(SCAN_QUEUE),
        latest=(SCAN_QUEUE[-1].asset_tag if SCAN_QUEUE else ""),
        equipment_type=(session.get("equipment_type") or "laptop").strip() or "laptop",
        slot_options=slot_options,
        case_options=case_options,
    )


@app.post("/add-assets/review")
@require_login
@require_role("admin")
def add_assets_review():
    if len(SCAN_QUEUE) == 0:
        flash("Queue is empty. Add at least one asset to the queue before reviewing the batch.", "error")
        return redirect(url_for("add_assets"))

    return redirect(url_for("preview"))


@app.route("/bootstrap/admin", methods=["GET", "POST"])
def bootstrap_admin():
    if count_users() != 0:
        return {"ok": False, "error": "Bootstrap is disabled"}, 403

    if request.method == "GET":
        return render_template("bootstrap_admin.html", error=None)

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    if not username or not password:
        return render_template("bootstrap_admin.html", error="Username and password are required."), 400
    if password != confirm_password:
        return render_template("bootstrap_admin.html", error="Passwords do not match."), 400

    try:
        user = create_user(username=username, password=password, role="admin", active=True)
    except ValueError as e:
        return render_template("bootstrap_admin.html", error=str(e)), 400
    except sqlite3.IntegrityError:
        return render_template("bootstrap_admin.html", error="Username already exists."), 400

    session["user_id"] = int(user["id"])
    touch_session()
    return redirect("/dashboard")


@app.get("/logout")
def logout():
    session.pop("user_id", None)
    return redirect("/")


@app.get("/account/change-password")
@require_login
def account_change_password():
    return render_template("account_change_password.html")


@app.post("/account/change-password")
@require_login
def account_change_password_submit():
    user = current_user()
    if user is None:
        return {"ok": False, "error": "Forbidden"}, 403

    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirm_new_password = request.form.get("confirm_new_password") or ""

    if new_password != confirm_new_password:
        flash("New password and confirmation must match.", "error")
        return redirect(url_for("account_change_password"))

    try:
        change_own_password(int(user["id"]), current_password, new_password)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("account_change_password"))

    flash("Password updated.", "success")
    return redirect(url_for("account_change_password"))


@app.get("/dashboard")
@require_login
def dashboard():
    threshold_days = get_custody_days_threshold(
        os.getenv("ASSETTRACK_CUSTODY_DAYS_THRESHOLD"),
        default=30,
    )

    conn = get_connection()
    try:
        dashboard_data = build_dashboard_data(
            conn,
            custody_days_threshold=threshold_days,
        )
    finally:
        conn.close()

    return render_template(
        "dashboard.html",
        dashboard=dashboard_data,
        custody_days_threshold=threshold_days,
    )


@app.get("/dashboard/holders")
@require_login
def dashboard_holders():
    conn = get_connection()
    try:
        holders = list_holders_in_custody(conn)
    finally:
        conn.close()

    return render_template(
        "dashboard_holders.html",
        holders=holders,
    )


@app.get("/dashboard/holders/<int:holder_id>")
@require_login
def dashboard_holder_detail(holder_id: int):
    conn = get_connection()
    try:
        detail = get_holder_custody_detail(conn, holder_id)
    finally:
        conn.close()

    if detail is None:
        abort(404)

    return render_template(
        "dashboard_holder_detail.html",
        holder=detail,
    )


@app.get("/dashboard/cases")
@require_login
def dashboard_cases():
    conn = get_connection()
    try:
        cases = list_case_summaries(conn)
    finally:
        conn.close()

    return render_template(
        "dashboard_cases.html",
        cases=cases,
    )


@app.get("/dashboard/cases/<case_name>")
@require_login
def dashboard_case_detail(case_name: str):
    conn = get_connection()
    try:
        detail = get_case_slot_detail(conn, case_name)
    finally:
        conn.close()

    if detail is None:
        abort(404)

    return render_template(
        "dashboard_case_detail.html",
        case_detail=detail,
    )


@app.get("/assets/search")
@require_login
def asset_search():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    form_state = {
        "asset_tag": (request.args.get("asset_tag") or "").strip().upper(),
        "serial_number": (request.args.get("serial_number") or "").strip(),
    }
    assets: list[dict] = []
    error_message: Optional[str] = None
    lookup_mode = "none"

    if form_state["asset_tag"] or form_state["serial_number"]:
        conn = get_connection()
        try:
            assets, error_message, lookup_mode = _lookup_asset_for_verification(
                conn,
                asset_tag=form_state["asset_tag"],
                serial_number=form_state["serial_number"],
            )
        finally:
            conn.close()

    return render_template(
        "asset_search.html",
        form=form_state,
        assets=assets,
        error_message=error_message,
        lookup_mode=lookup_mode,
    )


@app.get("/preview")
@require_login
def preview():
    parsed_rows = build_parsed_rows_from_queue()
    validation = validate_rows(parsed_rows)
    is_valid = bool(validation.get("valid")) if isinstance(validation, dict) else False

    if wants_json():
        rows = [r["data"] for r in parsed_rows]
        return {"count": len(rows), "valid": is_valid, "result": validation, "rows": rows}

    return render_template(
        "preview.html",
        row_count=len(parsed_rows),
        parsed_rows=parsed_rows,
        valid=is_valid,
        validation=validation,
        equipment_type=(session.get("equipment_type") or "laptop").strip() or "laptop",
        selected_holder=_selected_holder_from_session(),
        issue_mode=bool(session.get("issue_mode")),
        last_seen_age_seconds=seconds_since_last_seen(),
        timeout_seconds=INTAKE_TIMEOUT_SECONDS,
    )


@app.get("/preview/validate")
@require_login
def preview_validate():
    parsed_rows = build_parsed_rows_from_queue()
    result = validate_rows(parsed_rows)

    return {
        "row_count": len(parsed_rows),
        "valid": bool(result.get("valid")) if isinstance(result, dict) else False,
        "result": result,
    }

@app.post("/preview/mode")
@require_login
@require_role("admin")
def preview_mode():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    enabled = (request.form.get("issue_mode") or "").strip().lower() in {"on", "true", "1", "yes"}
    session["issue_mode"] = bool(enabled)

    # If turning off issue mode, clear holder selection to avoid confusion.
    if not enabled:
        session.pop("holder_id", None)

    touch_session()
    return redirect(url_for("preview"))

@app.post("/preview/discard")
@require_login
@require_role("admin")
def preview_discard():
    # Enforce auth and inactivity timeout for discard requests.
    authed = enforce_inactivity_timeout()
    return_to = (request.form.get("return_to") or "").strip()
    return_to_path = _return_to_path(return_to)
    if auth_enabled() and not authed:
        if wants_json():
            return {"ok": False, "discarded": 0, "error": "Locked"}, 401
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    discarded = len(SCAN_QUEUE)
    SCAN_QUEUE.clear()
    if return_to_path != "/issue":
        session.pop("holder_id", None)

    # Reset UI defaults back to laptop (same invariant as intake()).
    session["equipment_type"] = "laptop"
    touch_session()

    if wants_json():
        return {"ok": True, "discarded": discarded}

    flash("Batch discarded.", "success")
    if return_to.startswith("/") and not return_to.startswith("//"):
        return redirect(return_to)
    return redirect(url_for("add_assets"))

@app.post("/preview/commit")
@require_login
@require_role("admin")
def preview_commit():
    # Enforce auth and inactivity timeout for commit requests.
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Locked"}, 401
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    # Require deliberate confirmation before adding to the database.
    confirmed = (request.form.get("confirm_reviewed") or "").strip().lower() in {"on", "true", "1", "yes"}
    if not confirmed:
        if wants_json():
            return {
                "ok": False,
                "committed": 0,
                "error": "Please confirm you reviewed the batch before adding it.",
            }, 400
        flash("Please confirm you reviewed the batch before adding it.", "error")
        return redirect(url_for("preview"))

    issue_mode = bool(session.get("issue_mode"))

    # Normal intake commit mode

    if not issue_mode:
        parsed_rows = build_parsed_rows_from_queue()

        validation = validate_rows(parsed_rows)
        is_valid = bool(validation.get("valid")) if isinstance(validation, dict) else False
        if not is_valid:
            if wants_json():
                return {
                    "ok": False,
                    "committed": 0,
                    "error": "Validation failed",
                    "result": validation,
                }, 400
            flash("Fix the batch before adding to the database.", "error")
            return redirect(url_for("preview"))

        equipment_type = (session.get("equipment_type") or "").strip()
        if not equipment_type:
            if wants_json():
                return {
                    "ok": False,
                    "committed": 0,
                    "error": "Equipment type is required to create new assets",
                }, 400
            flash("Equipment type is required before adding new assets to the database.", "error")
            return redirect(url_for("preview"))

        try:
            result = commit_batch(parsed_rows)
        except BatchCommitError as e:
            if wants_json():
                return {"ok": False, "committed": 0, "error": str(e)}, 400
            flash(f"Could not add items to the database: {e}", "error")
            return redirect(url_for("preview"))

        SCAN_QUEUE.clear()
        session.pop("holder_id", None)  # keep tidy; holder is only meaningful for issue mode
        touch_session()

        if wants_json():
            return {"ok": True, "committed": result.committed_count}

        count = result.committed_count
        noun = "item" if count == 1 else "items"
        flash(f"Added {count} {noun} to the database.", "success")
        return redirect(url_for("add_assets"))

    # Issue commit mode

    holder = _selected_holder_from_session()
    if holder is None:
        if wants_json():
            return {
                "ok": False,
                "committed": 0,
                "error": "Select a holder before issuing assets.",
            }, 400
        flash("Select a holder before issuing assets.", "error")
        return redirect(url_for("preview"))

    issue_location_form, issue_location_errors, _ = _validate_issue_location_form(
        holder,
        _issue_location_form_from_session(),
    )
    if issue_location_errors:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "; ".join(issue_location_errors)}, 400
        flash("; ".join(issue_location_errors), "error")
        return redirect(url_for("issue"))

    asset_tags = _queue_asset_tags()

    try:
        committed_count = _issue_batch(asset_tags, holder["id"], issue_location_form)
    except ValueError as e:
        if wants_json():
            return {"ok": False, "committed": 0, "error": str(e)}, 400
        flash(f"Issue failed: {e}", "error")
        return redirect(url_for("preview"))

    SCAN_QUEUE.clear()
    touch_session()

    if wants_json():
        return {"ok": True, "committed": committed_count}

    flash(f"Issue {committed_count} assets.", "success")
    return redirect(url_for("issue"))


@app.get("/issue")
@require_login
def issue():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("add_assets"))

    if not bool(session.get("issue_mode")):
        session["issue_mode"] = True

    if session.get("last_seen") is None:
        touch_session()

    selected_holder = _selected_holder_from_session()
    if selected_holder is None:
        flash("Select a holder before issuing assets.", "error")
        return redirect(url_for("holders_search", return_to=url_for("issue")))

    issue_location_form, issue_location_errors, issue_location_context = _validate_issue_location_form(
        selected_holder,
        _issue_location_form_from_session(),
    )
    session["issue_building"] = issue_location_form["building"]
    session["issue_room"] = issue_location_form["room"]
    asset_tags = _queue_asset_tags()
    issue_state = _build_issue_preview_state(asset_tags, selected_holder)
    issued_count_raw = (request.args.get("issued") or "").strip()
    issued_count = 0
    if issued_count_raw:
        try:
            issued_count = max(0, int(issued_count_raw))
        except ValueError:
            issued_count = 0
    workflow_banner_outcome = None
    if issued_count > 0 and not asset_tags:
        workflow_banner_outcome = (
            f"Issued {issued_count} asset successfully."
            if issued_count == 1
            else f"Issued {issued_count} assets successfully."
        )

    return render_template(
        "return_queue.html",
        page_title="Issue Assets",
        page_heading="Issue Assets",
        scan_heading="Scan issues",
        workflow_banner_title="Issuing Assets",
        workflow_banner_queued_count=len(asset_tags),
        workflow_banner_outcome=workflow_banner_outcome,
        return_to=url_for("issue"),
        preview_url=url_for("issue_preview"),
        preview_label="Open Issue Assets Preview / Confirm",
        auth_enabled=auth_enabled(),
        authed=is_authed(),
        last_seen_age_seconds=seconds_since_last_seen(),
        timeout_seconds=INTAKE_TIMEOUT_SECONDS,
        queue=SCAN_QUEUE,
        queue_len=len(SCAN_QUEUE),
        latest=(SCAN_QUEUE[-1].asset_tag if SCAN_QUEUE else ""),
        equipment_type=(session.get("equipment_type") or "laptop").strip() or "laptop",
        queued_count=len(asset_tags),
        ready_count=issue_state["ready_count"],
        blocking_issues=issue_state["blocking_issues"],
        selected_holder=selected_holder,
        issue_location_form=issue_location_form,
        issue_location_errors=issue_location_errors,
        issue_location_building_options=issue_location_context["building_options"],
        issue_location_constrained_by_org=issue_location_context["constrained_by_org"],
        issue_location_ready=not issue_location_errors,
        issue_location_label=_issue_location_label(issue_location_form),
    )


@app.post("/issue/location")
@require_login
def issue_location_update():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("add_assets"))

    selected_holder = _selected_holder_from_session()
    if selected_holder is None:
        flash("Select a holder before issuing assets.", "error")
        return redirect(url_for("holders_search", return_to=url_for("issue")))

    issue_location_form, issue_location_errors, _ = _validate_issue_location_form(
        selected_holder,
        {
            "building": (request.form.get("building") or "").strip(),
            "room": (request.form.get("room") or "").strip(),
        },
    )
    session["issue_building"] = issue_location_form["building"]
    session["issue_room"] = issue_location_form["room"]
    touch_session()

    if issue_location_errors:
        flash("; ".join(issue_location_errors), "error")
    else:
        flash(f"Current location set to {_issue_location_label(issue_location_form)}.", "success")

    return redirect(url_for("issue"))


@app.get("/issue/preview")
@require_login
def issue_preview():
    issue_mode = bool(session.get("issue_mode"))
    if not issue_mode:
        flash("Use the Issue workflow before opening Issue Assets Preview.", "error")
        return redirect(url_for("issue"))

    selected_holder = _selected_holder_from_session()
    issue_location_form, issue_location_errors, issue_location_context = _validate_issue_location_form(
        selected_holder,
        _issue_location_form_from_session(),
    )
    session["issue_building"] = issue_location_form["building"]
    session["issue_room"] = issue_location_form["room"]
    asset_tags = _queue_asset_tags()
    issue_preview_state = _build_issue_preview_state(asset_tags, selected_holder)

    return render_template(
        "issue_preview.html",
        issue_mode=issue_mode,
        selected_holder=selected_holder,
        workflow_banner_title="Confirm Issue",
        workflow_banner_queued_count=len(asset_tags),
        queued_count=len(asset_tags),
        assets=issue_preview_state["assets"],
        ready_count=issue_preview_state["ready_count"],
        blocking_issues=issue_preview_state["blocking_issues"],
        last_seen_age_seconds=seconds_since_last_seen(),
        timeout_seconds=INTAKE_TIMEOUT_SECONDS,
        issue_location_form=issue_location_form,
        issue_location_errors=issue_location_errors,
        issue_location_building_options=issue_location_context["building_options"],
        issue_location_constrained_by_org=issue_location_context["constrained_by_org"],
        issue_location_label=_issue_location_label(issue_location_form),
    )


@app.post("/issue/commit")
@require_login
def issue_commit():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Locked"}, 401
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("issue"))

    issue_mode = bool(session.get("issue_mode"))
    if not issue_mode:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Issue mode is not enabled."}, 400
        flash("Enable issue mode before issuing assets.", "error")
        return redirect(url_for("preview"))

    confirmed = (request.form.get("confirm_reviewed") or "").strip().lower() in {"on", "true", "1", "yes"}
    if not confirmed:
        if wants_json():
            return {
                "ok": False,
                "committed": 0,
                "error": "Please confirm you reviewed the batch before adding it.",
            }, 400
        flash("Please confirm you reviewed the batch before adding it.", "error")
        return redirect(url_for("issue_preview"))

    holder = _selected_holder_from_session()
    if holder is None:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Select a holder before issuing assets."}, 400
        flash("Select a holder before issuing assets.", "error")
        return redirect(url_for("issue_preview"))

    issue_location_form, issue_location_errors, _ = _validate_issue_location_form(
        holder,
        _issue_location_form_from_session(),
    )
    if issue_location_errors:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "; ".join(issue_location_errors)}, 400
        flash("; ".join(issue_location_errors), "error")
        return redirect(url_for("issue"))

    asset_tags = _queue_asset_tags()
    if not asset_tags:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "No assets in the queue to issue."}, 400
        flash("No assets in the queue to issue..", "error")
        return redirect(url_for("issue_preview"))

    try:
        committed_count = _issue_batch(asset_tags, holder["id"], issue_location_form)
    except ValueError as e:
        if wants_json():
            return {"ok": False, "committed": 0, "error": str(e)}, 400
        flash(f"Issue failed: {e}", "error")
        return redirect(url_for("issue_preview"))

    SCAN_QUEUE.clear()
    touch_session()

    if wants_json():
        return {"ok": True, "committed": committed_count, "error": None}

    flash(f"Issued {committed_count} assets.", "success")
    return redirect(url_for("issue", issued=committed_count))


@app.get("/return")
@require_login
def return_queue():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Locked"}, 401
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    asset_tags = _queue_asset_tags()
    state = _build_return_preview_state(asset_tags)
    recent_return_cases_raw = session.pop("recent_return_cases", [])
    recent_return_cases = [str(case_name) for case_name in recent_return_cases_raw if str(case_name or "").strip()]

    if wants_json():
        return {
            "ok": len(state["blocking_issues"]) == 0,
            "committed": 0,
            "error": "; ".join(state["blocking_issues"]) if state["blocking_issues"] else None,
            "queued": asset_tags,
            "ready_count": state["ready_count"],
            "items": state["assets"],
        }

    return render_template(
        "return_queue.html",
        workflow_banner_title="Returning Assets",
        workflow_banner_destination="Home slots",
        workflow_banner_queued_count=len(asset_tags),
        queued_count=len(asset_tags),
        ready_count=state["ready_count"],
        blocking_issues=state["blocking_issues"],
        recent_return_cases=recent_return_cases,
        queue=SCAN_QUEUE,
        queue_len=len(SCAN_QUEUE),
        last_seen_age_seconds=seconds_since_last_seen(),
        timeout_seconds=INTAKE_TIMEOUT_SECONDS,
    )


@app.get("/return/preview")
@require_login
def return_preview():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Locked"}, 401
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    asset_tags = _queue_asset_tags()
    state = _build_return_preview_state(asset_tags)

    return render_template(
        "return_preview.html",
        workflow_banner_title="Confirm Return",
        workflow_banner_destination="Home slots",
        workflow_banner_queued_count=len(asset_tags),
        queued_count=len(asset_tags),
        preview_rows=state["assets"],
        ready_count=state["ready_count"],
        blocking_issues=state["blocking_issues"],
        last_seen_age_seconds=seconds_since_last_seen(),
        timeout_seconds=INTAKE_TIMEOUT_SECONDS,
    )


@app.post("/return/commit")
@require_login
def return_commit():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Locked"}, 401
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    confirmed = (request.form.get("confirm_reviewed") or "").strip().lower() in {"on", "true", "1", "yes"}
    if not confirmed:
        if wants_json():
            return {
                "ok": False,
                "committed": 0,
                "error": "Please confirm you reviewed the batch before returning assets.",
            }, 400
        flash("Please confirm you reviewed the batch before returning assets.", "error")
        return redirect(url_for("return_preview"))

    asset_tags = _queue_asset_tags()
    state = _build_return_preview_state(asset_tags)
    if state["blocking_issues"]:
        message = "; ".join(state["blocking_issues"])
        if wants_json():
            return {"ok": False, "committed": 0, "error": message}, 400
        flash(f"Return failed: {message}", "error")
        return redirect(url_for("return_preview"))

    try:
        committed_count = _return_batch(asset_tags)
    except ValueError as e:
        if wants_json():
            return {"ok": False, "committed": 0, "error": str(e)}, 400
        flash(f"Return failed: {e}", "error")
        return redirect(url_for("return_preview"))

    SCAN_QUEUE.clear()
    touch_session()
    returned_cases: list[str] = []
    for row in state["assets"]:
        case_name = str(row.get("destination_case_name") or "").strip()
        if case_name and case_name not in returned_cases:
            returned_cases.append(case_name)
    session["recent_return_cases"] = returned_cases

    if wants_json():
        return {"ok": True, "committed": committed_count, "error": None}

    if committed_count == 1 and len(state["assets"]) == 1:
        returned_asset = state["assets"][0]
        flash(
            "Returned "
            f"{returned_asset['canonical_tag'] or returned_asset['scanned_tag']}. "
            f"Location: {returned_asset['after_location_type']}. "
            f"Slot: {returned_asset['destination_slot']}.",
            "success",
        )
    else:
        flash(f"Returned {committed_count} assets.", "success")
    return redirect(url_for("return_queue"))

@app.get("/lock")
@require_login
@require_role("admin")
def lock():
    set_authed(False)
    return redirect("/")

@app.get("/holders")
@require_login
def holders_search():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    query = (request.args.get("q") or "").strip()
    return_to = (request.args.get("return_to") or "").strip()
    results = search_holders(query) if query else list_holders()

    return render_template(
        "holders_search.html",
        query=query,
        return_to=return_to,
        results=results,
        selected_holder=_selected_holder_from_session(),
    )


@app.get("/holders/list")
@require_login
def holders_list():
    return redirect(url_for("holders_search"))


@app.get("/holders/<int:holder_id>")
@require_login
def holder_detail(holder_id: int):
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    return_to = (request.args.get("return_to") or "").strip()
    holder = get_holder(holder_id)
    if holder is None:
        abort(404)

    conn = get_connection()
    try:
        detail = get_holder_custody_detail(conn, holder_id)
    finally:
        conn.close()

    assigned_assets = detail["assets"] if detail is not None else []
    return render_template(
        "holder_detail.html",
        holder=holder,
        assigned_assets=assigned_assets,
        asset_count=len(assigned_assets),
        return_to=return_to,
    )


@app.get("/holders/new")
@require_login
def holders_new():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    return_to = _safe_local_return_to(request.args.get("return_to") or "")
    form = session.pop("holder_new_form", None)
    if not isinstance(form, dict):
        form = {"name": "", "organization_id": ""}

    return render_template(
        "holder_new.html",
        form=form,
        return_to=return_to,
        organization_options=list_organizations(),
    )


@app.post("/holders/new")
@require_login
def holders_create():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    return_to = _safe_local_return_to(request.form.get("return_to") or "")
    name = (request.form.get("name") or "").strip()
    organization_id_raw = (request.form.get("organization_id") or "").strip()
    form = {"name": name, "organization_id": organization_id_raw}

    try:
        created = create_holder(
            name,
            organization_id=None if not organization_id_raw else int(organization_id_raw),
        )
    except ValueError as e:
        session["holder_new_form"] = form
        flash(_holder_form_error_message(e), "error")
        if return_to is not None:
            return redirect(url_for("holders_new", return_to=return_to))
        return redirect(url_for("holders_new"))

    flash(f"Created holder: {_holder_display_name(created)}", "success")
    if return_to is not None:
        return redirect(return_to)
    return redirect(url_for("holders_search"))


@app.get("/holders/edit/<int:holder_id>")
@require_login
def holders_edit(holder_id: int):
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    return_to = _safe_local_return_to(request.args.get("return_to") or "")
    holder = get_holder(holder_id)
    if holder is None:
        abort(404)

    form = session.pop(f"holder_edit_form:{holder_id}", None)
    if not isinstance(form, dict):
        form = {
            "name": str(holder.get("name") or ""),
            "organization_id": "" if holder.get("organization_id") is None else str(holder.get("organization_id")),
        }

    return render_template(
        "holder_edit.html",
        holder=holder,
        form=form,
        return_to=return_to,
        organization_options=list_organizations(),
    )


@app.post("/holders/edit/<int:holder_id>")
@require_login
def holders_edit_submit(holder_id: int):
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    return_to = _safe_local_return_to(request.form.get("return_to") or "")
    form = {
        "name": (request.form.get("name") or "").strip(),
        "organization_id": (request.form.get("organization_id") or "").strip(),
    }

    holder = get_holder(holder_id)
    if holder is None:
        abort(404)

    try:
        updated = update_holder(
            holder_id,
            name=form["name"],
            organization_id=None if not form["organization_id"] else int(form["organization_id"]),
        )
    except ValueError as e:
        session[f"holder_edit_form:{holder_id}"] = form
        flash(_holder_form_error_message(e), "error")
        if return_to is not None:
            return redirect(url_for("holders_edit", holder_id=holder_id, return_to=return_to))
        return redirect(url_for("holders_edit", holder_id=holder_id))

    flash(f"Updated holder: {_holder_display_name(updated)}", "success")
    if return_to is not None:
        return redirect(return_to)
    return redirect(url_for("holders_search"))


@app.post("/holders/select")
@require_login
def holders_select():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    return_to = (request.form.get("return_to") or "").strip()
    holder_id_raw = (request.form.get("holder_id") or "").strip()
    if not holder_id_raw:
        flash("Select a holder first.", "error")
        if return_to.startswith("/") and not return_to.startswith("//"):
            return redirect(url_for("holders_search", return_to=return_to))
        return redirect(url_for("holders_search"))

    holder = get_holder(holder_id_raw)
    if holder is None:
        flash("Selected holder not found.", "error")
        if return_to.startswith("/") and not return_to.startswith("//"):
            return redirect(url_for("holders_search", return_to=return_to))
        return redirect(url_for("holders_search"))

    session["holder_id"] = holder["id"]
    touch_session()
    flash(f"Selected holder: {_holder_display_name(holder)}", "success")
    if return_to.startswith("/") and not return_to.startswith("//"):
        return redirect(return_to)
    return redirect(url_for("holders_search"))


@app.post("/holders/clear")
@require_login
def holders_clear():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    session.pop("holder_id", None)
    touch_session()
    flash("Cleared holder selection.", "success")
    return redirect(url_for("holders_search"))


@app.get("/admin/users")
@require_login
@require_role("admin")
def admin_users():
    users = list_users()
    return render_template("admin_users.html", users=users)


@app.get("/admin/system")
@require_login
@require_role("admin")
def admin_system():
    resolved_db_path = _resolved_runtime_db_path()
    holder_count: int | None = None
    asset_count: int | None = None
    schema_warning: str | None = None

    try:
        conn = sqlite3.connect(f"file:{resolved_db_path}?mode=ro", uri=True)
        try:
            holder_count = int(conn.execute("SELECT COUNT(*) FROM holders;").fetchone()[0])
            asset_count = int(conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error as exc:
        schema_warning = f"Could not read system health data: {exc}"

    return render_template(
        "admin_system.html",
        db_path=str(resolved_db_path),
        holder_count=holder_count,
        asset_count=asset_count,
        schema_warning=schema_warning,
    )


@app.route("/admin/reference-data", methods=["GET", "POST"])
@require_login
@require_role("admin")
def admin_reference_data():
    error_message: str | None = None

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        try:
            if action == "create_organization":
                create_organization((request.form.get("organization_name") or "").strip())
                flash("Created organization.", "success")
            elif action == "create_building":
                create_building((request.form.get("building_name") or "").strip())
                flash("Created building.", "success")
            elif action == "map_organization_building":
                create_organization_building_mapping(
                    int((request.form.get("organization_id") or "").strip()),
                    int((request.form.get("building_id") or "").strip()),
                )
                flash("Created organization to building mapping.", "success")
            else:
                error_message = "Unknown action."
        except ValueError as e:
            error_message = str(e)

    return render_template(
        "admin_reference_data.html",
        organizations=list_organizations(),
        buildings=list_buildings(),
        mappings=list_organization_building_mappings(),
        error_message=error_message,
    )


@app.get("/admin/db/export")
@require_login
@require_role("admin")
def admin_db_export():
    resolved_db_path = _resolved_runtime_db_path()
    if not resolved_db_path.exists() or not resolved_db_path.is_file():
        return "Database file not found.", 404

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    download_name = f"assettrack-backup-{timestamp}.db"
    return send_file(
        resolved_db_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/octet-stream",
        conditional=False,
    )


@app.post("/admin/users/create")
@require_login
@require_role("admin")
def admin_users_create():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    role = (request.form.get("role") or "").strip().lower()
    active = True if request.form.get("active") is None else _is_truthy(request.form.get("active"))

    try:
        create_user(username=username, password=password, role=role, active=active)
    except ValueError as e:
        flash(str(e), "error")
    except sqlite3.IntegrityError:
        flash("Username already exists.", "error")
    else:
        flash(f"Created user: {username}", "success")

    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/toggle-active")
@require_login
@require_role("admin")
def admin_users_toggle_active(user_id: int):
    target = get_user_by_id(user_id)
    if target is None:
        flash("User not found.", "error")
        return redirect(url_for("admin_users"))

    requested = request.form.get("active")
    next_active = (not bool(int(target.get("active") or 0))) if requested is None else _is_truthy(requested)

    try:
        updated = set_user_active(user_id, next_active)
    except ValueError as e:
        flash(str(e), "error")
    else:
        state = "enabled" if int(updated.get("active") or 0) == 1 else "disabled"
        flash(f"User {updated['username']} is now {state}.", "success")

    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/reset-password")
@require_login
@require_role("admin")
def admin_users_reset_password(user_id: int):
    new_password = request.form.get("new_password") or ""

    try:
        updated = reset_user_password(user_id, new_password)
    except ValueError as e:
        flash(str(e), "error")
    else:
        flash(f"Password reset for {updated['username']}.", "success")

    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/set-role")
@require_login
@require_role("admin")
def admin_users_set_role(user_id: int):
    role = (request.form.get("role") or "").strip().lower()

    try:
        updated = set_user_role(user_id, role)
    except ValueError as e:
        flash(str(e), "error")
    else:
        flash(f"Updated role for {updated['username']} to {updated['role']}.", "success")

    return redirect(url_for("admin_users"))


@app.route("/admin/assets/new", methods=["GET", "POST"])
@require_login
@require_role("admin")
def admin_new_asset():
    guard_result = _require_admin_for_route()
    if guard_result:
        return guard_result

    form_state = {
        "asset_tag": "",
        "serial_number": "",
        "manufacturer": "",
        "equipment_type": "laptop",
        "building": "",
        "room": "",
        "model": "",
        "model_code": "",
        "notes": "",
        "case_name": "",
        "slot_id": "",
    }
    error_message: Optional[str] = None
    conn = get_connection()
    try:
        slot_options = _list_slot_options(conn)
        case_options = _slot_case_options(slot_options)

        if request.method == "POST":
            form_state = {
                "asset_tag": (request.form.get("asset_tag") or "").strip().upper(),
                "serial_number": (request.form.get("serial_number") or "").strip(),
                "manufacturer": (request.form.get("manufacturer") or "").strip(),
                "equipment_type": (request.form.get("equipment_type") or "").strip() or "laptop",
                "building": (request.form.get("building") or "").strip(),
                "room": (request.form.get("room") or "").strip(),
                "model": (request.form.get("model") or "").strip(),
                "model_code": (request.form.get("model_code") or "").strip(),
                "notes": (request.form.get("notes") or "").strip(),
                "case_name": (request.form.get("case_name") or "").strip().upper(),
                "slot_id": (request.form.get("slot_id") or "").strip(),
            }

            selected_slot, errors = _validate_admin_new_asset_form(conn, form_state)

            if errors:
                error_message = "; ".join(errors)
                return render_template(
                    "admin_new_asset.html",
                    form=form_state,
                    error_message=error_message,
                    equipment_type_options=ASSET_EQUIPMENT_TYPE_OPTIONS,
                    slot_options=slot_options,
                    case_options=case_options,
                )

            try:
                conn.execute("BEGIN;")
                _create_admin_asset_in_tx(
                    conn,
                    asset_tag=form_state["asset_tag"],
                    actor="admin",
                    equipment_type=form_state["equipment_type"],
                    serial_number=form_state["serial_number"],
                    manufacturer=form_state["manufacturer"],
                    building=form_state["building"],
                    room=form_state["room"],
                    model=form_state["model"] or None,
                    model_code=form_state["model_code"] or None,
                    notes=form_state["notes"] or None,
                    assign_case_number=None if selected_slot is None else str(selected_slot["case_name"]),
                    assign_slot_number=None if selected_slot is None else int(selected_slot["slot_position"]),
                )
                conn.commit()
            except ValueError as e:
                conn.rollback()
                error_message = _humanize_admin_asset_create_error(str(e))
                return render_template(
                    "admin_new_asset.html",
                    form=form_state,
                    error_message=error_message,
                    equipment_type_options=ASSET_EQUIPMENT_TYPE_OPTIONS,
                    slot_options=slot_options,
                    case_options=case_options,
                )
            except sqlite3.IntegrityError as e:
                conn.rollback()
                error_message = f"create failed: {e}"
                return render_template(
                    "admin_new_asset.html",
                    form=form_state,
                    error_message=error_message,
                    equipment_type_options=ASSET_EQUIPMENT_TYPE_OPTIONS,
                    slot_options=slot_options,
                    case_options=case_options,
                )
            except Exception:
                conn.rollback()
                raise

            flash(f"Created asset {form_state['asset_tag']}.", "success")
            return redirect(url_for("admin_new_asset"))
    finally:
        conn.close()

    return render_template(
        "admin_new_asset.html",
        form=form_state,
        error_message=error_message,
        equipment_type_options=ASSET_EQUIPMENT_TYPE_OPTIONS,
        slot_options=slot_options,
        case_options=case_options,
    )


@app.route("/admin/assets/edit", methods=["GET", "POST"])
@require_login
@require_role("admin")
def admin_edit_asset():
    guard_result = _require_admin_for_route()
    if guard_result:
        return guard_result

    form_state = {
        "lookup_asset_tag": (request.args.get("asset_tag") or "").strip().upper(),
        "asset_tag": "",
        "serial_number": "",
        "manufacturer": "",
        "equipment_type": "",
        "building": "",
        "room": "",
        "model": "",
        "model_code": "",
        "notes": "",
        "case_name": "",
        "slot_id": "",
    }
    asset_view: Optional[dict] = None
    error_message: Optional[str] = None

    conn = get_connection()
    try:
        slot_options = _list_slot_options(conn)
        case_options = _slot_case_options(slot_options)

        if form_state["lookup_asset_tag"]:
            asset_view, blocking_errors = _build_admin_edit_asset_view(conn, form_state["lookup_asset_tag"])
            if asset_view:
                selected_home_slot = asset_view["home_slot"] or asset_view["current_slot"]
                form_state.update(
                    {
                        "asset_tag": asset_view["asset_tag"],
                        "serial_number": asset_view["serial_number"],
                        "manufacturer": asset_view["manufacturer"],
                        "equipment_type": asset_view["equipment_type"],
                        "building": asset_view["building"],
                        "room": asset_view["room"],
                        "model": asset_view["model"],
                        "model_code": asset_view["model_code"],
                        "notes": asset_view["notes"],
                        "case_name": "" if selected_home_slot is None else str(selected_home_slot["case_name"]),
                        "slot_id": "" if selected_home_slot is None else str(selected_home_slot["slot_id"]),
                    }
                )
            elif blocking_errors:
                error_message = "; ".join(blocking_errors)

        if request.method == "POST":
            action = (request.form.get("action") or "lookup").strip().lower()
            lookup_asset_tag = (request.form.get("lookup_asset_tag") or "").strip().upper()
            form_state["lookup_asset_tag"] = lookup_asset_tag

            if action == "lookup":
                asset_view, blocking_errors = _build_admin_edit_asset_view(conn, lookup_asset_tag)
                if asset_view:
                    selected_home_slot = asset_view["home_slot"] or asset_view["current_slot"]
                    form_state.update(
                        {
                            "asset_tag": asset_view["asset_tag"],
                            "serial_number": asset_view["serial_number"],
                            "manufacturer": asset_view["manufacturer"],
                            "equipment_type": asset_view["equipment_type"],
                            "building": asset_view["building"],
                            "room": asset_view["room"],
                            "model": asset_view["model"],
                            "model_code": asset_view["model_code"],
                            "notes": asset_view["notes"],
                            "case_name": "" if selected_home_slot is None else str(selected_home_slot["case_name"]),
                            "slot_id": "" if selected_home_slot is None else str(selected_home_slot["slot_id"]),
                        }
                    )
                elif not lookup_asset_tag:
                    error_message = "asset_tag is required."
                elif blocking_errors:
                    error_message = "; ".join(blocking_errors)
            elif action == "update":
                form_state.update(
                    {
                        "asset_tag": (request.form.get("asset_tag") or "").strip().upper(),
                        "serial_number": (request.form.get("serial_number") or "").strip(),
                        "manufacturer": (request.form.get("manufacturer") or "").strip(),
                        "equipment_type": (request.form.get("equipment_type") or "").strip(),
                        "building": (request.form.get("building") or "").strip(),
                        "room": (request.form.get("room") or "").strip(),
                        "model": (request.form.get("model") or "").strip(),
                        "model_code": (request.form.get("model_code") or "").strip(),
                        "notes": (request.form.get("notes") or "").strip(),
                        "case_name": (request.form.get("case_name") or "").strip().upper(),
                        "slot_id": (request.form.get("slot_id") or "").strip(),
                    }
                )
                asset_view, blocking_errors = _build_admin_edit_asset_view(conn, lookup_asset_tag or form_state["asset_tag"])
                if asset_view is None:
                    error_message = "; ".join(blocking_errors or ["asset_tag not found"])
                    return render_template(
                        "admin_edit_asset.html",
                        form=form_state,
                        asset=asset_view,
                        error_message=error_message,
                        slot_options=slot_options,
                        case_options=case_options,
                    )

                errors: list[str] = []
                if not form_state["serial_number"]:
                    errors.append("serial_number is required.")
                if not form_state["manufacturer"]:
                    errors.append("manufacturer is required.")
                if not form_state["equipment_type"]:
                    errors.append("equipment_type is required.")
                if not form_state["building"]:
                    errors.append("building is required.")
                if not form_state["room"]:
                    errors.append("room is required.")

                selected_slot, slot_errors = _resolve_slot_selection(
                    conn,
                    case_name=form_state["case_name"],
                    slot_id_raw=form_state["slot_id"],
                )
                errors.extend(slot_errors)

                if errors:
                    error_message = "; ".join(errors)
                    return render_template(
                        "admin_edit_asset.html",
                        form=form_state,
                        asset=asset_view,
                        error_message=error_message,
                        slot_options=slot_options,
                        case_options=case_options,
                    )

                try:
                    conn.execute("BEGIN;")
                    _update_admin_asset_in_tx(
                        conn,
                        asset_id=int(asset_view["id"]),
                        actor="admin",
                        serial_number=form_state["serial_number"],
                        manufacturer=form_state["manufacturer"],
                        equipment_type=form_state["equipment_type"],
                        building=form_state["building"],
                        room=form_state["room"],
                        model=form_state["model"] or None,
                        model_code=form_state["model_code"] or None,
                        notes=form_state["notes"] or None,
                        selected_slot=selected_slot,
                    )
                    conn.commit()
                except ValueError as e:
                    conn.rollback()
                    error_message = str(e)
                    return render_template(
                        "admin_edit_asset.html",
                        form=form_state,
                        asset=asset_view,
                        error_message=error_message,
                        slot_options=slot_options,
                        case_options=case_options,
                    )
                except sqlite3.IntegrityError as e:
                    conn.rollback()
                    error_message = f"update failed: {e}"
                    return render_template(
                        "admin_edit_asset.html",
                        form=form_state,
                        asset=asset_view,
                        error_message=error_message,
                        slot_options=slot_options,
                        case_options=case_options,
                    )
                except Exception:
                    conn.rollback()
                    raise

                flash(f"Updated asset {form_state['asset_tag']}.", "success")
                return redirect(url_for("admin_edit_asset", asset_tag=form_state["asset_tag"]))
            elif action == "cleanup":
                target_asset_tag = lookup_asset_tag or (request.form.get("asset_tag") or "").strip().upper()
                asset_view, blocking_errors = _build_admin_edit_asset_view(conn, target_asset_tag)
                if asset_view is None:
                    error_message = "; ".join(blocking_errors or ["asset_tag not found"])
                    return render_template(
                        "admin_edit_asset.html",
                        form=form_state,
                        asset=asset_view,
                        error_message=error_message,
                        slot_options=slot_options,
                        case_options=case_options,
                    )

                selected_home_slot = asset_view["home_slot"] or asset_view["current_slot"]
                form_state.update(
                    {
                        "asset_tag": asset_view["asset_tag"],
                        "serial_number": asset_view["serial_number"],
                        "manufacturer": asset_view["manufacturer"],
                        "equipment_type": asset_view["equipment_type"],
                        "building": asset_view["building"],
                        "room": asset_view["room"],
                        "model": asset_view["model"],
                        "model_code": asset_view["model_code"],
                        "notes": asset_view["notes"],
                        "case_name": "" if selected_home_slot is None else str(selected_home_slot["case_name"]),
                        "slot_id": "" if selected_home_slot is None else str(selected_home_slot["slot_id"]),
                    }
                )

                try:
                    conn.execute("BEGIN;")
                    asset_row = _find_asset_for_scan_tag(conn, asset_view["asset_tag"])
                    if asset_row is None:
                        raise ValueError("asset_tag not found")

                    cleanup_state = _build_admin_asset_cleanup_state(conn, asset_row)
                    if not cleanup_state["allowed"]:
                        raise ValueError("; ".join(cleanup_state["reasons"]))

                    deleted = conn.execute(
                        "DELETE FROM assets WHERE id = ?;",
                        (int(asset_row["id"]),),
                    )
                    if deleted.rowcount != 1:
                        raise ValueError("Asset could not be removed.")

                    conn.commit()
                except ValueError as e:
                    conn.rollback()
                    error_message = str(e)
                    asset_view, _ = _build_admin_edit_asset_view(conn, target_asset_tag)
                    return render_template(
                        "admin_edit_asset.html",
                        form=form_state,
                        asset=asset_view,
                        error_message=error_message,
                        slot_options=slot_options,
                        case_options=case_options,
                    )
                except Exception:
                    conn.rollback()
                    raise

                flash(f"Removed junk asset {asset_view['asset_tag']}.", "success")
                return redirect(url_for("admin_edit_asset"))
            else:
                error_message = "Unknown action."
    finally:
        conn.close()

    return render_template(
        "admin_edit_asset.html",
        form=form_state,
        asset=asset_view,
        error_message=error_message,
        slot_options=slot_options,
        case_options=case_options,
    )


@app.route("/admin/assets/retire", methods=["GET", "POST"])
@require_login
@require_role("admin")
def admin_retire_asset():
    guard_result = _require_admin_for_route()
    if guard_result:
        return guard_result

    form_state = {
        "asset_tag": "",
        "failure_type": "",
        "notes": "",
        "confirm_physical": False,
        "confirm_in_field": False,
    }
    asset_view: Optional[dict] = None
    error_message: Optional[str] = None

    if request.method == "POST":
        action = (request.form.get("action") or "lookup").strip().lower()
        form_state = {
            "asset_tag": (request.form.get("asset_tag") or "").strip().upper(),
            "failure_type": (request.form.get("failure_type") or "").strip().upper(),
            "notes": (request.form.get("notes") or "").strip(),
            "confirm_physical": _is_truthy(request.form.get("confirm_physical")),
            "confirm_in_field": _is_truthy(request.form.get("confirm_in_field")),
        }

        conn = get_connection()
        try:
            asset_view, blocking_errors = _build_admin_retire_asset_view(conn, form_state["asset_tag"])
            if action == "lookup":
                if not form_state["asset_tag"]:
                    error_message = "asset_tag is required."
                elif blocking_errors:
                    error_message = "; ".join(blocking_errors)
            elif action == "retire":
                errors: list[str] = []
                if not form_state["asset_tag"]:
                    errors.append("asset_tag is required.")
                if not form_state["failure_type"]:
                    errors.append("failure_type is required.")
                elif form_state["failure_type"] not in RETIRE_FAILURE_TYPES:
                    errors.append(
                        f"failure_type must be one of: {', '.join(sorted(RETIRE_FAILURE_TYPES))}."
                    )
                if not form_state["notes"]:
                    errors.append("notes is required.")
                if not form_state["confirm_physical"]:
                    errors.append("You must confirm physical reality before retiring.")
                if asset_view and asset_view["location_type"] == "IN_CUSTODY" and not form_state["confirm_in_field"]:
                    errors.append("You must confirm the in-custody asset is not recoverable.")
                if blocking_errors:
                    errors.extend(blocking_errors)
                if errors:
                    error_message = "; ".join(errors)
                    return render_template(
                        "admin_retire_asset.html",
                        form=form_state,
                        asset=asset_view,
                        error_message=error_message,
                        failure_type_options=sorted(RETIRE_FAILURE_TYPES),
                    )

                try:
                    conn.execute("BEGIN;")
                    result = _retire_admin_asset_in_tx(
                        conn,
                        asset_id=int(asset_view["id"]),
                        asset_tag=str(asset_view["asset_tag"]),
                        failure_type=form_state["failure_type"],
                        notes=form_state["notes"],
                        actor="admin",
                    )
                    conn.commit()
                except ValueError as e:
                    conn.rollback()
                    error_message = str(e)
                    return render_template(
                        "admin_retire_asset.html",
                        form=form_state,
                        asset=asset_view,
                        error_message=error_message,
                        failure_type_options=sorted(RETIRE_FAILURE_TYPES),
                    )
                except sqlite3.IntegrityError as e:
                    conn.rollback()
                    error_message = f"retire failed: {e}"
                    return render_template(
                        "admin_retire_asset.html",
                        form=form_state,
                        asset=asset_view,
                        error_message=error_message,
                        failure_type_options=sorted(RETIRE_FAILURE_TYPES),
                    )
                except Exception:
                    conn.rollback()
                    raise

                flash(
                    f"Retired asset {result['asset_tag']} with status {result['to_location_type']}.",
                    "success",
                )
                return redirect(url_for("admin_retire_asset"))
            else:
                error_message = "Unknown action."
        finally:
            conn.close()

    return render_template(
        "admin_retire_asset.html",
        form=form_state,
        asset=asset_view,
        error_message=error_message,
        failure_type_options=sorted(RETIRE_FAILURE_TYPES),
    )


@app.route("/admin/assets/replace", methods=["GET", "POST"])
@require_login
@require_role("admin")
def admin_replace_asset():
    guard_result = _require_admin_for_route()
    if guard_result:
        return guard_result

    form_state = {
        "failed_asset_tag": "",
        "failure_type": "",
        "failure_notes": "",
        "replacement_asset_tag": "",
        "replacement_serial_number": "",
        "replacement_manufacturer": "",
        "replacement_equipment_type": "laptop",
        "replacement_model": "",
        "replacement_model_code": "",
        "replacement_notes": "",
        "confirm_retire": False,
        "confirm_slot": False,
    }
    failed_asset_view: Optional[dict] = None
    error_message: Optional[str] = None

    if request.method == "POST":
        action = (request.form.get("action") or "lookup").strip().lower()
        form_state = {
            "failed_asset_tag": (request.form.get("failed_asset_tag") or "").strip().upper(),
            "failure_type": (request.form.get("failure_type") or "").strip().upper(),
            "failure_notes": (request.form.get("failure_notes") or "").strip(),
            "replacement_asset_tag": (request.form.get("replacement_asset_tag") or "").strip().upper(),
            "replacement_serial_number": (request.form.get("replacement_serial_number") or "").strip(),
            "replacement_manufacturer": (request.form.get("replacement_manufacturer") or "").strip(),
            "replacement_equipment_type": (request.form.get("replacement_equipment_type") or "").strip() or "laptop",
            "replacement_model": (request.form.get("replacement_model") or "").strip(),
            "replacement_model_code": (request.form.get("replacement_model_code") or "").strip(),
            "replacement_notes": (request.form.get("replacement_notes") or "").strip(),
            "confirm_retire": _is_truthy(request.form.get("confirm_retire")),
            "confirm_slot": _is_truthy(request.form.get("confirm_slot")),
        }

        conn = get_connection()
        try:
            failed_asset_view, blocking_errors = _build_admin_replace_asset_view(conn, form_state["failed_asset_tag"])
            if action == "lookup":
                if not form_state["failed_asset_tag"]:
                    error_message = "failed asset_tag is required."
                elif blocking_errors:
                    error_message = "; ".join(blocking_errors)
            elif action == "replace":
                errors: list[str] = []
                if not form_state["failed_asset_tag"]:
                    errors.append("failed asset_tag is required.")
                if not form_state["failure_type"]:
                    errors.append("failure_type is required.")
                elif form_state["failure_type"] not in RETIRE_FAILURE_TYPES:
                    errors.append(
                        f"failure_type must be one of: {', '.join(sorted(RETIRE_FAILURE_TYPES))}."
                    )
                if not form_state["failure_notes"]:
                    errors.append("failure notes are required.")
                if not form_state["replacement_asset_tag"]:
                    errors.append("replacement asset_tag is required.")
                if not form_state["replacement_serial_number"]:
                    errors.append("replacement serial_number is required.")
                if not form_state["replacement_manufacturer"]:
                    errors.append("replacement manufacturer is required.")
                if not form_state["replacement_equipment_type"]:
                    errors.append("replacement equipment_type is required.")
                if not form_state["confirm_retire"]:
                    errors.append("You must confirm the failed asset is being retired.")
                if not form_state["confirm_slot"]:
                    errors.append("You must confirm the replacement will go into the target slot.")
                if blocking_errors:
                    errors.extend(blocking_errors)
                if errors:
                    error_message = "; ".join(errors)
                    return render_template(
                        "admin_replace_asset.html",
                        form=form_state,
                        failed_asset=failed_asset_view,
                        error_message=error_message,
                        failure_type_options=sorted(RETIRE_FAILURE_TYPES),
                    )

                try:
                    conn.execute("BEGIN;")
                    locked_failed = conn.execute(
                        """
                        SELECT id, asset_tag, location_type, current_holder_id, home_slot_id
                        FROM assets
                        WHERE id = ?
                        LIMIT 1;
                        """,
                        (int(failed_asset_view["id"]),),
                    ).fetchone()
                    if not locked_failed:
                        raise ValueError("failed asset_tag not found.")

                    locked_location = _normalize_location_type(locked_failed["location_type"])
                    if _is_terminal_location_type(locked_location):
                        raise ValueError("Failed asset is already retired/disposed.")
                    if locked_location not in {"STORAGE", "IN_CUSTODY"}:
                        raise ValueError("Failed asset must be in STORAGE or IN_CUSTODY.")

                    target_slot_id, target_slot = _resolve_replacement_target_slot(
                        conn,
                        failed_asset_id=int(locked_failed["id"]),
                        failed_asset_tag=str(locked_failed["asset_tag"]),
                        failed_home_slot_id=locked_failed["home_slot_id"],
                    )

                    replacement_tag_exists = conn.execute(
                        """
                        SELECT 1
                        FROM assets
                        WHERE UPPER(asset_tag) = UPPER(?)
                        LIMIT 1;
                        """,
                        (form_state["replacement_asset_tag"],),
                    ).fetchone()
                    if replacement_tag_exists:
                        raise ValueError("replacement asset_tag already exists.")

                    replacement_serial_exists = conn.execute(
                        """
                        SELECT 1
                        FROM assets
                        WHERE TRIM(COALESCE(serial_number, '')) <> ''
                          AND UPPER(serial_number) = UPPER(?)
                        LIMIT 1;
                        """,
                        (form_state["replacement_serial_number"],),
                    ).fetchone()
                    if replacement_serial_exists:
                        raise ValueError("replacement serial_number already exists.")

                    _validate_swap_target_slot_integrity(
                        conn,
                        target_slot_id=target_slot_id,
                        failed_asset_id=int(locked_failed["id"]),
                        failed_asset_tag=str(locked_failed["asset_tag"]),
                    )

                    _retire_admin_asset_in_tx(
                        conn,
                        asset_id=int(locked_failed["id"]),
                        asset_tag=str(locked_failed["asset_tag"]),
                        failure_type=form_state["failure_type"],
                        notes=form_state["failure_notes"],
                        actor="admin",
                    )

                    _create_admin_asset_in_tx(
                        conn,
                        asset_tag=form_state["replacement_asset_tag"],
                        actor="admin",
                        equipment_type=form_state["replacement_equipment_type"],
                        serial_number=form_state["replacement_serial_number"],
                        manufacturer=form_state["replacement_manufacturer"],
                        building=str(failed_asset_view.get("building_room") or "").split("/", 1)[0],
                        room=str(failed_asset_view.get("building_room") or "").split("/", 1)[1]
                        if "/" in str(failed_asset_view.get("building_room") or "")
                        else "",
                        model=form_state["replacement_model"] or None,
                        model_code=form_state["replacement_model_code"] or None,
                        notes=form_state["replacement_notes"] or None,
                        assign_case_number=str(target_slot["case_name"]),
                        assign_slot_number=int(target_slot["slot_position"]),
                    )

                    conn.commit()
                except ValueError as e:
                    conn.rollback()
                    error_message = str(e)
                    return render_template(
                        "admin_replace_asset.html",
                        form=form_state,
                        failed_asset=failed_asset_view,
                        error_message=error_message,
                        failure_type_options=sorted(RETIRE_FAILURE_TYPES),
                    )
                except sqlite3.IntegrityError as e:
                    conn.rollback()
                    error_message = f"replace failed: {e}"
                    return render_template(
                        "admin_replace_asset.html",
                        form=form_state,
                        failed_asset=failed_asset_view,
                        error_message=error_message,
                        failure_type_options=sorted(RETIRE_FAILURE_TYPES),
                    )
                except Exception:
                    conn.rollback()
                    raise

                flash(
                    f"Replaced {form_state['failed_asset_tag']} with {form_state['replacement_asset_tag']} "
                    f"in case {target_slot['case_name']} slot {target_slot['slot_position']}.",
                    "success",
                )
                return redirect(url_for("admin_replace_asset"))
            else:
                error_message = "Unknown action."
        finally:
            conn.close()

    return render_template(
        "admin_replace_asset.html",
        form=form_state,
        failed_asset=failed_asset_view,
        error_message=error_message,
        failure_type_options=sorted(RETIRE_FAILURE_TYPES),
    )


@app.post("/admin/events/correct")
@require_login
@require_role("admin")
def admin_correct_event():
    guard_result = _require_admin_for_api()
    if guard_result:
        return guard_result

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return {"ok": False, "error": "JSON body must be an object"}, 400

    raw_supersedes = data.get("supersedes_event_id")
    correction_reason = str(data.get("correction_reason") or "").strip()

    try:
        supersedes_event_id = int(str(raw_supersedes).strip())
    except (TypeError, ValueError):
        return {"ok": False, "error": "supersedes_event_id must be an integer"}, 400

    if not correction_reason:
        return {"ok": False, "error": "correction_reason is required"}, 400

    conn = get_connection()
    try:
        original = _get_event_by_id(conn, supersedes_event_id)
        if original is None:
            return {"ok": False, "error": f"event {supersedes_event_id} not found"}, 404

        if _event_already_superseded(conn, supersedes_event_id):
            return {"ok": False, "error": f"event {supersedes_event_id} is already superseded"}, 409

        # Copy-from-original defaults, with explicit override support
        asset_tag = str(data.get("asset_tag") or original.get("asset_tag") or "").strip()
        event_type = str(data.get("event_type") or original.get("event_type") or "").strip()
        event_date = str(data.get("event_date") or original.get("event_date") or "").strip()
        actor = str(data.get("actor") or original.get("actor") or "admin").strip()

        notes_value = data.get("notes", None)
        if notes_value is None:
            notes_value = original.get("notes")
        notes = str(notes_value) if notes_value is not None else None

        payload = data.get("payload", None)
        if payload is None:
            try:
                payload = json.loads(original.get("payload") or "null")
            except (TypeError, ValueError):
                payload = None

        if not asset_tag:
            return {"ok": False, "error": "asset_tag is required"}, 400
        if not event_type:
            return {"ok": False, "error": "event_type is required"}, 400
        if not event_date:
            return {"ok": False, "error": "event_date is required"}, 400

        # Keep payload predictable: only dicts become JSON; everything else => None
        payload_dict = payload if isinstance(payload, dict) else None

        try:
            conn.execute("BEGIN;")
            record_event(
                conn,
                asset_tag=asset_tag,
                event_type=event_type,
                event_date=event_date,
                actor=actor or "admin",
                notes=notes,
                payload=payload_dict,
                supersedes_event_id=supersedes_event_id,
                correction_reason=correction_reason,
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            conn.rollback()
            return {"ok": False, "error": f"correction failed: {e}"}, 400
        except Exception:
            conn.rollback()
            raise

        return (
            {
                "ok": True,
                "supersedes_event_id": supersedes_event_id,
                "asset_tag": asset_tag,
                "event_type": event_type,
            },
            201,
        )
    finally:
        conn.close()


@app.post("/admin/assets/create")
@require_login
@require_role("admin")
def admin_create_asset():
    guard_result = _require_admin_for_api()
    if guard_result:
        return guard_result

    raw_data = request.get_json(silent=True)
    if not isinstance(raw_data, dict):
        raw_data = request.form.to_dict()

    asset_tag = str(raw_data.get("asset_tag") or "").strip().upper()
    actor = str(raw_data.get("actor") or "").strip()
    equipment_type_raw = str(raw_data.get("equipment_type") or "").strip()
    serial_number = str(raw_data.get("serial_number") or "").strip()
    manufacturer = str(raw_data.get("manufacturer") or "").strip()
    building = str(raw_data.get("building") or "").strip()
    room = str(raw_data.get("room") or "").strip()
    model = str(raw_data.get("model") or "").strip() or None
    model_code = str(raw_data.get("model_code") or "").strip() or None
    notes_raw = str(raw_data.get("notes") or "").strip()
    home_slot_raw = raw_data.get("home_slot_id")

    equipment_type = equipment_type_raw or ""
    notes = notes_raw or None

    errors: list[str] = []
    if not asset_tag:
        errors.append("asset_tag is required.")
    if not actor:
        errors.append("actor is required.")

    home_slot_id: Optional[int] = None
    if home_slot_raw is not None and str(home_slot_raw).strip() != "":
        try:
            home_slot_id = int(str(home_slot_raw).strip())
        except ValueError:
            errors.append("home_slot_id must be an integer.")

    if errors:
        return {"ok": False, "error": "; ".join(errors)}, 400

    conn = get_connection()
    try:
        try:
            conn.execute("BEGIN;")
            assign_case_number: Optional[str] = None
            assign_slot_number: Optional[int] = None
            if home_slot_id is not None:
                slot_row = conn.execute(
                    """
                    SELECT id, case_name, slot_position
                    FROM slots
                    WHERE id = ?
                    LIMIT 1;
                    """,
                    (home_slot_id,),
                ).fetchone()
                if slot_row is None:
                    raise ValueError("home_slot_id does not reference an existing slot.")
                assign_case_number = str(slot_row["case_name"])
                assign_slot_number = int(slot_row["slot_position"])

            created = _create_admin_asset_in_tx(
                conn,
                asset_tag=asset_tag,
                actor=actor,
                equipment_type=equipment_type,
                serial_number=serial_number,
                manufacturer=manufacturer,
                building=building,
                room=room,
                model=model,
                model_code=model_code,
                notes=notes,
                assign_case_number=assign_case_number,
                assign_slot_number=assign_slot_number,
            )

            conn.commit()
        except ValueError as e:
            conn.rollback()
            return {"ok": False, "error": str(e)}, 400
        except sqlite3.IntegrityError as e:
            conn.rollback()
            return {"ok": False, "error": f"create failed: {e}"}, 400
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

    return {
        "ok": True,
        "asset_tag": asset_tag,
        "location_type": str(created["location_type"]),
        "current_holder_id": created["current_holder_id"],
        "home_slot_id": created["home_slot_id"],
        "event_type": "ASSET_CREATED",
    }


@app.route("/admin/assign-slot", methods=["GET", "POST"])
@require_login
@require_role("admin")
def admin_assign_slot():
    guard_result = _require_admin_for_route()
    if guard_result:
        return guard_result

    asset_tag = ""
    building_room = ""
    case_number = ""
    slot_number = ""
    notes = ""
    asset_view: Optional[dict] = None

    if request.method == "POST":
        action = (request.form.get("action") or "lookup").strip().lower()
        asset_tag = (request.form.get("asset_tag") or "").strip()
        building_room = (request.form.get("building_room") or "").strip()
        case_number = (request.form.get("case_number") or "").strip().upper()
        slot_number = (request.form.get("slot_number") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        conn = get_connection()
        try:
            asset_view, blocking_errors = _build_admin_assign_asset_view(conn, asset_tag)

            if action == "lookup":
                if not asset_tag:
                    flash("asset_tag is required.", "error")
                elif blocking_errors:
                    for msg in blocking_errors:
                        flash(msg, "error")
                else:
                    flash(f"Asset {asset_view['asset_tag']} is eligible for slot assignment.", "success")
            elif action == "assign":
                if not asset_tag:
                    flash("asset_tag is required.", "error")
                if not building_room:
                    flash("building/room is required.", "error")
                if not case_number:
                    flash("case_number is required.", "error")
                if not slot_number:
                    flash("slot_number is required.", "error")

                if not asset_tag or not building_room or not case_number or not slot_number:
                    return render_template(
                        "admin_assign_slot.html",
                        asset_tag=asset_tag,
                        building_room=building_room,
                        case_number=case_number,
                        slot_number=slot_number,
                        notes=notes,
                        asset=asset_view,
                    )

                if blocking_errors:
                    for msg in blocking_errors:
                        flash(msg, "error")
                    return render_template(
                        "admin_assign_slot.html",
                        asset_tag=asset_tag,
                        building_room=building_room,
                        case_number=case_number,
                        slot_number=slot_number,
                        notes=notes,
                        asset=asset_view,
                    )

                try:
                    slot_position = int(slot_number)
                except ValueError:
                    flash("slot_number must be an integer.", "error")
                    return render_template(
                        "admin_assign_slot.html",
                        asset_tag=asset_tag,
                        building_room=building_room,
                        case_number=case_number,
                        slot_number=slot_number,
                        notes=notes,
                        asset=asset_view,
                    )

                try:
                    conn.execute("BEGIN;")

                    asset_row = _find_asset_for_scan_tag(conn, asset_tag)
                    if not asset_row:
                        raise ValueError("asset_tag not found")

                    location_type = _normalize_location_type(asset_row.get("location_type"))
                    if _is_terminal_location_type(location_type):
                        raise ValueError("Asset is retired/disposed and cannot be assigned to a slot.")
                    if location_type != "STORAGE":
                        raise ValueError("Asset must be location_type=STORAGE.")
                    if location_type == "IN_CUSTODY":
                        raise ValueError("Asset is IN_CUSTODY and cannot be assigned to a slot.")

                    occupied_by_asset = conn.execute(
                        """
                        SELECT 1
                        FROM slot_occupancy
                        WHERE asset_id = ?
                        LIMIT 1;
                        """,
                        (asset_row["id"],),
                    ).fetchone()
                    legacy_occupied_by_asset = conn.execute(
                        """
                        SELECT 1
                        FROM slots
                        WHERE UPPER(current_asset_tag) = UPPER(?)
                           OR REPLACE(UPPER(current_asset_tag), '-', '') = UPPER(?)
                        LIMIT 1;
                        """,
                        (asset_row["asset_tag"], asset_row["asset_tag"]),
                    ).fetchone()
                    if occupied_by_asset or legacy_occupied_by_asset:
                        raise ValueError("Asset is already slotted.")

                    slot = conn.execute(
                        """
                        SELECT id, case_name, slot_position, current_asset_tag
                        FROM slots
                        WHERE UPPER(case_name) = UPPER(?)
                          AND slot_position = ?
                        LIMIT 1;
                        """,
                        (case_number, slot_position),
                    ).fetchone()
                    if not slot:
                        raise ValueError("Selected slot does not exist.")

                    occupied_by_slot = conn.execute(
                        """
                        SELECT 1
                        FROM slot_occupancy
                        WHERE slot_id = ?
                        LIMIT 1;
                        """,
                        (slot["id"],),
                    ).fetchone()
                    if occupied_by_slot:
                        raise ValueError("Selected slot is already occupied.")
                    legacy_slot_occupied = str(slot["current_asset_tag"] or "").strip()
                    if legacy_slot_occupied:
                        raise ValueError("Selected slot is already occupied.")

                    now_iso = datetime.now(timezone.utc).isoformat()

                    conn.execute(
                        """
                        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
                        VALUES (?, ?, ?);
                        """,
                        (slot["id"], asset_row["id"], now_iso),
                    )

                    conn.execute(
                        """
                        UPDATE slots
                        SET current_asset_tag = ?
                        WHERE id = ?;
                        """,
                        (asset_row["asset_tag"], slot["id"]),
                    )

                    asset_columns = get_asset_table_columns(conn)
                    update_clauses: list[str] = []
                    update_values: list[object] = []
                    if "home_slot_id" in asset_columns:
                        update_clauses.append("home_slot_id = ?")
                        update_values.append(slot["id"])
                    if "building_room" in asset_columns:
                        update_clauses.append("building_room = ?")
                        update_values.append(building_room)
                    if "case_number" in asset_columns:
                        update_clauses.append("case_number = ?")
                        update_values.append(case_number)
                    if "slot_number" in asset_columns:
                        update_clauses.append("slot_number = ?")
                        update_values.append(str(slot_position))
                    if "updated_date" in asset_columns:
                        update_clauses.append("updated_date = ?")
                        update_values.append(now_iso)
                    if update_clauses:
                        update_values.append(asset_row["id"])
                        conn.execute(
                            f"UPDATE assets SET {', '.join(update_clauses)} WHERE id = ?;",
                            tuple(update_values),
                        )

                    payload = {
                        "slot_id": int(slot["id"]),
                        "building_room": building_room,
                        "case_number": str(slot["case_name"]),
                        "slot_number": int(slot["slot_position"]),
                    }
                    conn.execute(
                        """
                        INSERT INTO asset_events (
                            asset_tag,
                            event_type,
                            event_date,
                            actor,
                            notes,
                            payload,
                            holder_id
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            str(asset_row["asset_tag"]),
                            "SLOT_ASSIGN",
                            now_iso,
                            "admin",
                            notes or None,
                            json.dumps(payload),
                            None,
                        ),
                    )

                    conn.commit()
                except ValueError as e:
                    conn.rollback()
                    flash(str(e), "error")
                    asset_view, _ = _build_admin_assign_asset_view(conn, asset_tag)
                    return render_template(
                        "admin_assign_slot.html",
                        asset_tag=asset_tag,
                        building_room=building_room,
                        case_number=case_number,
                        slot_number=slot_number,
                        notes=notes,
                        asset=asset_view,
                    )
                except Exception:
                    conn.rollback()
                    raise

                flash(
                    f"Assigned asset {asset_row['asset_tag']} to {slot['case_name']} slot {slot['slot_position']}.",
                    "success",
                )
                return redirect(url_for("admin_assign_slot"))
            else:
                flash("Unknown action.", "error")
        finally:
            conn.close()

    return render_template(
        "admin_assign_slot.html",
        asset_tag=asset_tag,
        building_room=building_room,
        case_number=case_number,
        slot_number=slot_number,
        notes=notes,
        asset=asset_view,
    )


@app.route("/admin/slot-move", methods=["GET", "POST"])
@require_login
@require_role("admin")
def admin_slot_move():
    guard_result = _require_admin_for_route()
    if guard_result:
        return guard_result

    source_slot_id_raw = (request.args.get("slot_id") or request.form.get("source_slot_id") or "").strip()
    source_slot_id: Optional[int] = None
    source_slot: Optional[dict] = None
    building_room = ""
    case_number = ""
    slot_number = ""
    notes = ""

    if source_slot_id_raw:
        try:
            source_slot_id = int(source_slot_id_raw)
        except ValueError:
            flash("slot_id must be an integer.", "error")

    conn = get_connection()
    try:
        if source_slot_id is not None:
            source_slot = _build_admin_slot_move_source_view(conn, source_slot_id)
            if source_slot:
                asset = source_slot.get("asset") or {}
                building_room = str(asset.get("building_room") or "")
                case_number = str(source_slot.get("case_name") or "")
                slot_number = str(source_slot.get("slot_position") or "")
            elif request.method == "GET":
                flash("Source slot not found.", "error")
        elif request.method == "GET":
            flash("slot_id is required.", "error")

        if request.method == "POST":
            building_room = (request.form.get("building_room") or "").strip()
            case_number = (request.form.get("case_number") or "").strip().upper()
            slot_number = (request.form.get("slot_number") or "").strip()
            notes = (request.form.get("notes") or "").strip()

            if source_slot_id is None:
                flash("slot_id is required.", "error")
                return render_template(
                    "admin_slot_move.html",
                    source_slot=source_slot,
                    source_slot_id=source_slot_id_raw,
                    building_room=building_room,
                    case_number=case_number,
                    slot_number=slot_number,
                    notes=notes,
                )

            if not building_room:
                flash("building/room is required.", "error")
            if not case_number:
                flash("case_number is required.", "error")
            if not slot_number:
                flash("slot_number is required.", "error")
            if not source_slot or not source_slot.get("occupied"):
                flash("Source slot is missing or empty.", "error")

            if not building_room or not case_number or not slot_number or not source_slot or not source_slot.get("occupied"):
                return render_template(
                    "admin_slot_move.html",
                    source_slot=source_slot,
                    source_slot_id=source_slot_id,
                    building_room=building_room,
                    case_number=case_number,
                    slot_number=slot_number,
                    notes=notes,
                )

            try:
                destination_slot_position = int(slot_number)
            except ValueError:
                flash("slot_number must be an integer.", "error")
                return render_template(
                    "admin_slot_move.html",
                    source_slot=source_slot,
                    source_slot_id=source_slot_id,
                    building_room=building_room,
                    case_number=case_number,
                    slot_number=slot_number,
                    notes=notes,
                )

            try:
                conn.execute("BEGIN;")

                source_slot_locked = conn.execute(
                    """
                    SELECT s.id, s.case_name, s.slot_position, so.asset_id, a.asset_tag, a.location_type
                    FROM slots s
                    LEFT JOIN slot_occupancy so ON so.slot_id = s.id
                    LEFT JOIN assets a ON a.id = so.asset_id
                    WHERE s.id = ?
                    LIMIT 1;
                    """,
                    (source_slot_id,),
                ).fetchone()
                if not source_slot_locked:
                    raise ValueError("Source slot is missing or empty.")
                if source_slot_locked["asset_id"] is None:
                    raise ValueError("Source slot is missing or empty.")

                asset_id = int(source_slot_locked["asset_id"])
                asset_tag = str(source_slot_locked["asset_tag"] or "")
                location_type = _normalize_location_type(source_slot_locked["location_type"])
                if _is_terminal_location_type(location_type):
                    raise ValueError("Asset is retired/disposed and cannot be moved.")
                if location_type != "STORAGE":
                    raise ValueError("Asset must be location_type=STORAGE.")
                if location_type == "IN_CUSTODY":
                    raise ValueError("Asset is IN_CUSTODY and cannot be moved.")

                destination_slot = conn.execute(
                    """
                    SELECT id, case_name, slot_position, current_asset_tag
                    FROM slots
                    WHERE UPPER(case_name) = UPPER(?)
                      AND slot_position = ?
                    LIMIT 1;
                    """,
                    (case_number, destination_slot_position),
                ).fetchone()
                if not destination_slot:
                    raise ValueError("Destination slot does not exist.")

                destination_slot_id = int(destination_slot["id"])
                if destination_slot_id == int(source_slot_locked["id"]):
                    raise ValueError("Moving to the same slot is not allowed.")

                destination_occupied = conn.execute(
                    """
                    SELECT 1
                    FROM slot_occupancy
                    WHERE slot_id = ?
                    LIMIT 1;
                    """,
                    (destination_slot_id,),
                ).fetchone()
                if destination_occupied:
                    raise ValueError("Destination slot is already occupied.")
                if str(destination_slot["current_asset_tag"] or "").strip():
                    raise ValueError("Destination slot is already occupied.")

                extra_asset_slot = conn.execute(
                    """
                    SELECT slot_id
                    FROM slot_occupancy
                    WHERE asset_id = ? AND slot_id <> ?
                    LIMIT 1;
                    """,
                    (asset_id, source_slot_id),
                ).fetchone()
                if extra_asset_slot:
                    raise ValueError("Asset already appears in another slot.")

                delete_source = conn.execute(
                    """
                    DELETE FROM slot_occupancy
                    WHERE slot_id = ? AND asset_id = ?;
                    """,
                    (source_slot_id, asset_id),
                )
                if delete_source.rowcount != 1:
                    raise ValueError("Source slot is missing or empty.")

                now_iso = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
                    VALUES (?, ?, ?);
                    """,
                    (destination_slot_id, asset_id, now_iso),
                )

                conn.execute(
                    """
                    UPDATE slots
                    SET current_asset_tag = NULL
                    WHERE id = ?;
                    """,
                    (source_slot_id,),
                )
                conn.execute(
                    """
                    UPDATE slots
                    SET current_asset_tag = ?
                    WHERE id = ?;
                    """,
                    (asset_tag, destination_slot_id),
                )

                asset_columns = get_asset_table_columns(conn)
                update_clauses: list[str] = []
                update_values: list[object] = []
                if "home_slot_id" in asset_columns:
                    update_clauses.append("home_slot_id = ?")
                    update_values.append(destination_slot_id)
                if "building_room" in asset_columns:
                    update_clauses.append("building_room = ?")
                    update_values.append(building_room)
                if "case_number" in asset_columns:
                    update_clauses.append("case_number = ?")
                    update_values.append(str(destination_slot["case_name"]))
                if "slot_number" in asset_columns:
                    update_clauses.append("slot_number = ?")
                    update_values.append(str(destination_slot["slot_position"]))
                if "updated_date" in asset_columns:
                    update_clauses.append("updated_date = ?")
                    update_values.append(now_iso)
                if update_clauses:
                    update_values.append(asset_id)
                    conn.execute(
                        f"UPDATE assets SET {', '.join(update_clauses)} WHERE id = ?;",
                        tuple(update_values),
                    )

                payload = {
                    "from_slot": {
                        "slot_id": int(source_slot_locked["id"]),
                        "case_number": str(source_slot_locked["case_name"] or ""),
                        "slot_number": int(source_slot_locked["slot_position"]),
                    },
                    "to_slot": {
                        "slot_id": destination_slot_id,
                        "building_room": building_room,
                        "case_number": str(destination_slot["case_name"] or ""),
                        "slot_number": int(destination_slot["slot_position"]),
                    },
                }
                conn.execute(
                    """
                    INSERT INTO asset_events (
                        asset_tag,
                        event_type,
                        event_date,
                        actor,
                        notes,
                        payload,
                        holder_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        asset_tag,
                        "SLOT_MOVE",
                        now_iso,
                        "admin",
                        notes or None,
                        json.dumps(payload),
                        None,
                    ),
                )

                conn.commit()
            except ValueError as e:
                conn.rollback()
                flash(str(e), "error")
                source_slot = _build_admin_slot_move_source_view(conn, source_slot_id)
                return render_template(
                    "admin_slot_move.html",
                    source_slot=source_slot,
                    source_slot_id=source_slot_id,
                    building_room=building_room,
                    case_number=case_number,
                    slot_number=slot_number,
                    notes=notes,
                )
            except Exception:
                conn.rollback()
                raise

            flash(
                f"Moved asset {asset_tag} from {source_slot_locked['case_name']} slot {source_slot_locked['slot_position']} "
                f"to {destination_slot['case_name']} slot {destination_slot['slot_position']}.",
                "success",
            )
            return redirect(url_for("admin_slot_move", slot_id=destination_slot_id))
    finally:
        conn.close()

    return render_template(
        "admin_slot_move.html",
        source_slot=source_slot,
        source_slot_id=source_slot_id,
        building_room=building_room,
        case_number=case_number,
        slot_number=slot_number,
        notes=notes,
    )


@app.route("/admin/force-vacate", methods=["GET", "POST"])
@require_login
@require_role("admin")
def admin_force_vacate():
    guard_result = _require_admin_for_route()
    if guard_result:
        return guard_result

    slot_id_raw = (request.args.get("slot_id") or request.form.get("slot_id") or "").strip()
    slot_id: Optional[int] = None
    slot_view: Optional[dict] = None
    reason = ""
    notes = ""
    confirmed = False

    if slot_id_raw:
        try:
            slot_id = int(slot_id_raw)
        except ValueError:
            flash("slot_id must be an integer.", "error")

    conn = get_connection()
    try:
        if slot_id is not None:
            slot_view = _build_admin_force_vacate_view(conn, slot_id)
            if slot_view is None and request.method == "GET":
                flash("Slot not found.", "error")
        elif request.method == "GET":
            flash("slot_id is required.", "error")

        if request.method == "POST":
            reason = (request.form.get("reason") or "").strip()
            notes = (request.form.get("notes") or "").strip()
            confirmed = (request.form.get("confirm_empty") or "").strip().lower() in {"on", "true", "1", "yes"}

            if slot_id is None:
                flash("slot_id is required.", "error")
            if slot_view is None:
                flash("Slot not found.", "error")
            if slot_view and not slot_view.get("occupied"):
                flash("Cannot force vacate an empty slot.", "error")

            asset_for_view = (slot_view or {}).get("asset") if slot_view else None
            if asset_for_view and _normalize_location_type(asset_for_view.get("location_type")) == "IN_CUSTODY":
                flash("Cannot force vacate: occupied asset is IN_CUSTODY.", "error")
            if asset_for_view and _is_terminal_location_type(asset_for_view.get("location_type")):
                flash("Cannot force vacate: occupied asset is retired/disposed.", "error")
            if not reason:
                flash("Reason is required.", "error")
            if not confirmed:
                flash("You must confirm physical verification before force vacate.", "error")

            if (
                slot_id is None
                or slot_view is None
                or not slot_view.get("occupied")
                or not reason
                or not confirmed
                or (asset_for_view and _normalize_location_type(asset_for_view.get("location_type")) == "IN_CUSTODY")
                or (asset_for_view and _is_terminal_location_type(asset_for_view.get("location_type")))
            ):
                return render_template(
                    "admin_force_vacate.html",
                    slot=slot_view,
                    slot_id=slot_id_raw,
                    reason=reason,
                    notes=notes,
                    confirmed=confirmed,
                )

            try:
                conn.execute("BEGIN;")

                locked = conn.execute(
                    """
                    SELECT
                        s.id AS slot_id,
                        s.case_name,
                        s.slot_position,
                        s.current_asset_tag,
                        so.asset_id AS occupancy_asset_id,
                        a.asset_tag AS occ_asset_tag,
                        a.manufacturer AS occ_manufacturer,
                        a.model AS occ_model,
                        a.serial_number AS occ_serial,
                        a.location_type AS occ_location_type,
                        a.building_room AS occ_building_room
                    FROM slots s
                    LEFT JOIN slot_occupancy so ON so.slot_id = s.id
                    LEFT JOIN assets a ON a.id = so.asset_id
                    WHERE s.id = ?
                    LIMIT 1;
                    """,
                    (slot_id,),
                ).fetchone()

                if not locked:
                    raise ValueError("Slot not found.")

                legacy_asset_tag = str(locked["current_asset_tag"] or "").strip()
                occupied = locked["occupancy_asset_id"] is not None or bool(legacy_asset_tag)
                if not occupied:
                    raise ValueError("Cannot force vacate an empty slot.")

                asset_id: Optional[int] = None
                asset_tag = ""
                asset_manufacturer = ""
                asset_model = ""
                asset_serial = ""
                asset_location_type = ""
                asset_building_room = ""

                if locked["occupancy_asset_id"] is not None:
                    asset_id = int(locked["occupancy_asset_id"])
                    asset_tag = str(locked["occ_asset_tag"] or "")
                    asset_manufacturer = str(locked["occ_manufacturer"] or "")
                    asset_model = str(locked["occ_model"] or "")
                    asset_serial = str(locked["occ_serial"] or "")
                    asset_location_type = str(locked["occ_location_type"] or "").strip().upper()
                    asset_building_room = str(locked["occ_building_room"] or "")
                elif legacy_asset_tag:
                    legacy_asset = _find_asset_for_scan_tag(conn, legacy_asset_tag)
                    if legacy_asset:
                        asset_id = int(legacy_asset["id"])
                        asset_tag = str(legacy_asset.get("asset_tag") or legacy_asset_tag)
                        asset_manufacturer = str(legacy_asset.get("manufacturer") or "")
                        asset_model = str(legacy_asset.get("model") or "")
                        asset_serial = str(legacy_asset.get("serial_number") or "")
                        asset_location_type = str(legacy_asset.get("location_type") or "").strip().upper()
                        asset_building_room = str(legacy_asset.get("building_room") or "")
                    else:
                        raise ValueError("Occupied asset record not found.")

                if _is_terminal_location_type(asset_location_type):
                    raise ValueError("Cannot force vacate: occupied asset is retired/disposed.")
                if asset_location_type == "IN_CUSTODY":
                    raise ValueError("Cannot force vacate: occupied asset is IN_CUSTODY.")

                conn.execute(
                    """
                    DELETE FROM slot_occupancy
                    WHERE slot_id = ?;
                    """,
                    (slot_id,),
                )

                conn.execute(
                    """
                    UPDATE slots
                    SET current_asset_tag = NULL
                    WHERE id = ?;
                    """,
                    (slot_id,),
                )

                now_iso = datetime.now(timezone.utc).isoformat()
                if asset_id is not None:
                    asset_columns = get_asset_table_columns(conn)
                    update_clauses: list[str] = []
                    update_values: list[object] = []
                    if "home_slot_id" in asset_columns:
                        update_clauses.append("home_slot_id = NULL")
                    if "location_type" in asset_columns:
                        update_clauses.append("location_type = ?")
                        update_values.append("STORAGE")
                    if "updated_date" in asset_columns:
                        update_clauses.append("updated_date = ?")
                        update_values.append(now_iso)
                    if update_clauses:
                        update_values.append(asset_id)
                        conn.execute(
                            f"UPDATE assets SET {', '.join(update_clauses)} WHERE id = ?;",
                            tuple(update_values),
                        )

                payload = {
                    "slot": {
                        "slot_id": int(locked["slot_id"]),
                        "building_room": asset_building_room,
                        "case_number": str(locked["case_name"] or ""),
                        "slot_number": int(locked["slot_position"]),
                    },
                    "asset": {
                        "asset_id": asset_id,
                        "asset_tag": asset_tag,
                        "building_room": asset_building_room,
                        "manufacturer": asset_manufacturer,
                        "model": asset_model,
                        "serial": asset_serial,
                    },
                    "reason": reason,
                    "notes": notes or None,
                }
                conn.execute(
                    """
                    INSERT INTO asset_events (
                        asset_tag,
                        event_type,
                        event_date,
                        actor,
                        notes,
                        payload,
                        holder_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        asset_tag,
                        "FORCE_VACATE",
                        now_iso,
                        "admin",
                        reason,
                        json.dumps(payload),
                        None,
                    ),
                )

                conn.commit()
            except ValueError as e:
                conn.rollback()
                flash(str(e), "error")
                slot_view = _build_admin_force_vacate_view(conn, slot_id)
                return render_template(
                    "admin_force_vacate.html",
                    slot=slot_view,
                    slot_id=slot_id,
                    reason=reason,
                    notes=notes,
                    confirmed=confirmed,
                )
            except Exception:
                conn.rollback()
                raise

            flash(
                f"Force vacated slot {locked['case_name']} slot {locked['slot_position']} for asset {asset_tag}.",
                "success",
            )
            return redirect(url_for("admin_force_vacate", slot_id=slot_id))
    finally:
        conn.close()

    return render_template(
        "admin_force_vacate.html",
        slot=slot_view,
        slot_id=slot_id,
        reason=reason,
        notes=notes,
        confirmed=confirmed,
    )


if __name__ == "__main__":
    # Local dev run (and container run).
    app.run(host="0.0.0.0", port=8000, debug=True)
