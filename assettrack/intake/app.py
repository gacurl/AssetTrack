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
from typing import Optional
from datetime import datetime, timezone

from flask import Flask, flash, redirect, render_template, request, session, url_for

from assettrack.assets import get_asset_table_columns
from assettrack.db import get_connection
from assettrack.ingest.validator import validate_rows
from assettrack.ingest.committer import BatchCommitError, commit_batch
from assettrack.intake.scan import Scan
from assettrack.intake.to_ingest import scan_to_ingest_row
from assettrack.holders import get_holder, search_holders
from assettrack.slots import vacate_slot_by_asset_tag_in_tx


app = Flask(__name__)
app.secret_key = os.getenv("ASSETTRACK_SECRET_KEY", "dev-not-secret")

# In-memory only: wiped on restart
SCAN_QUEUE: list[Scan] = []

INTAKE_PASSCODE = os.getenv("ASSETTRACK_INTAKE_CODE")
INTAKE_TIMEOUT_SECONDS = int(os.getenv("ASSETTRACK_INTAKE_TIMEOUT_SECONDS", "300"))  # default 5 min
TERMINAL_LOCATION_TYPE = "DISPOSED"
TERMINAL_LOCATION_TYPES = {"DISPOSED", "RETIRED"}
RETIRE_FAILURE_TYPES = {"HARDWARE", "LOST", "STOLEN", "DESTROYED", "OTHER"}


# Helpers

def now_seconds() -> int:
    return int(time.time())


def touch_session() -> None:
    session["last_seen"] = now_seconds()


def sanitize_scan(raw: str) -> str:
    """Keep only letters and numbers; drop tabs/newlines/suffix junk."""
    return "".join(ch for ch in raw if ch.isalnum())


def auth_enabled() -> bool:
    return bool(INTAKE_PASSCODE)


def is_authed() -> bool:
    """If no passcode is set, auth is disabled (always authed)."""
    return True if not auth_enabled() else bool(session.get("authed", False))


def set_authed(value: bool) -> None:
    if value:
        session["authed"] = True
        touch_session()
    else:
        session.pop("authed", None)
        session.pop("last_seen", None)


def auth_ok(submitted: str | None) -> bool:
    if not auth_enabled():
        return True
    return submitted == INTAKE_PASSCODE


def enforce_inactivity_timeout() -> bool:
    """
    If authed, lock after inactivity.
    Returns the post-enforcement authed state.
    """
    if not (auth_enabled() and is_authed()):
        return is_authed()

    last_seen = session.get("last_seen")
    if last_seen is None:
        # Authed but missing last_seen: initialize.
        touch_session()
        return True

    elapsed = now_seconds() - int(last_seen)
    if elapsed > INTAKE_TIMEOUT_SECONDS:
        set_authed(False)
        return False

    # Still valid: refresh activity.
    touch_session()
    return True


def seconds_since_last_seen() -> Optional[int]:
    last_seen = session.get("last_seen")
    if last_seen is None:
        return None
    return max(0, now_seconds() - int(last_seen))


def build_parsed_rows_from_queue() -> list[dict]:
    """
    Build rows in the validator/committer format:
      [{"row_number": 1, "data": {...}}, ...]
    Also inject session equipment_type for SCAN rows missing it.
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


def _require_admin_for_route():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    if auth_enabled():
        touch_session()
    return None


def _require_admin_for_api():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        return {"ok": False, "error": "Locked"}, 401

    if auth_enabled():
        touch_session()
    return None


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
        holder_label = selected_holder["name"] if not identifier else f"{selected_holder['name']} ({identifier})"

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

    def _canon_asset_row_for_scan_tag(conn, scan_tag: str) -> Optional[dict]:
        t = (scan_tag or "").strip()
        if not t:
            return None

        rows = conn.execute(
            """
            SELECT asset_tag, location_type, current_holder_id
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

    def _is_slotted(conn, canon_asset_tag: str) -> bool:
        t = (canon_asset_tag or "").strip()
        if not t:
            return False

        row = conn.execute(
            """
            SELECT 1
            FROM slots
            WHERE UPPER(current_asset_tag) = UPPER(?)
               OR REPLACE(UPPER(current_asset_tag), '-', '') = UPPER(?)
            LIMIT 1;
            """,
            (t, t),
        ).fetchone()
        return bool(row)

    conn = get_connection()
    try:
        asset_columns = get_asset_table_columns(conn)
        required_columns = {"location_type", "current_holder_id"}
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
                "canonical_tag": None,
                "before_location_type": "UNKNOWN",
                "after_location_type": "IN_CUSTODY",
                "before_holder": "null",
                "after_holder": holder_label or "(select holder)",
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
            row["canonical_tag"] = canon_tag

            before_location = str(asset_row["location_type"] or "").strip().upper()
            row["before_location_type"] = before_location or "UNKNOWN"
            if _is_terminal_location_type(before_location):
                row["asset_issues"].append("Asset is retired/disposed")
                retired_assets.append(canon_tag)

            before_holder_id = asset_row["current_holder_id"]
            row["before_holder"] = "null" if before_holder_id is None else str(before_holder_id)

            slotted = _is_slotted(conn, canon_tag)
            row["before_slot_occupancy"] = "occupied" if slotted else "vacant"

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


def _stock_out_batch(asset_tags: list[str], holder_id: int) -> int:
    if not asset_tags:
        raise ValueError("No assets in the queue to stock out")

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
            SELECT asset_tag, location_type
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

    def _is_slotted(conn, canon_asset_tag: str) -> bool:
        """
        Slot may store dashed canonical tag. We accept either:
          - exact match
          - match where dashes are removed from slot value
        """
        t = (canon_asset_tag or "").strip()
        if not t:
            return False

        row = conn.execute(
            """
            SELECT 1
            FROM slots
            WHERE UPPER(current_asset_tag) = UPPER(?)
               OR REPLACE(UPPER(current_asset_tag), '-', '') = UPPER(?)
            LIMIT 1;
            """,
            (t, t),
        ).fetchone()
        return bool(row)

    conn = get_connection()
    try:
        with conn:
            asset_columns = get_asset_table_columns(conn)
            required_columns = {"location_type", "current_holder_id"}
            missing_columns = sorted(required_columns - asset_columns)
            if missing_columns:
                raise ValueError(f"Assets table missing columns: {', '.join(missing_columns)}")

            unknown_tags: list[str] = []
            not_storage: list[str] = []
            retired_assets: list[str] = []
            not_slotted: list[str] = []

            # Map scan tags -> canonical DB tags (so we update/vacate consistently)
            canon_tags: list[str] = []

            for scan_tag in asset_tags:
                asset_row = _canon_asset_row_for_scan_tag(conn, scan_tag)
                if not asset_row:
                    unknown_tags.append(scan_tag)
                    continue

                canon_tag = str(asset_row["asset_tag"])
                canon_tags.append(canon_tag)

                location_type = str(asset_row["location_type"] or "").strip().upper()
                if _is_terminal_location_type(location_type):
                    retired_assets.append(canon_tag)
                if location_type != "STORAGE":
                    not_storage.append(canon_tag)

                if not _is_slotted(conn, canon_tag):
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

            for canon_tag in canon_tags:
                conn.execute(
                    """
                    UPDATE assets
                    SET location_type = ?, current_holder_id = ?
                    WHERE UPPER(asset_tag) = UPPER(?)
                       OR REPLACE(UPPER(asset_tag), '-', '') = UPPER(?);
                    """,
                    ("IN_CUSTODY", holder_id, canon_tag, canon_tag),
                )

                # Vacate uses canonical dashed form (what you put into slots).
                vacate_slot_by_asset_tag_in_tx(conn, canon_tag)

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
                    (canon_tag, "STOCK_OUT", now_iso, "system", None, None, holder_id),
                )

            return len(canon_tags)
    finally:
        conn.close()


def _stock_in_batch(asset_tags: list[str]) -> int:
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
                    (canon_tag, "STOCK_IN", now_iso, "system", None, None, None),
                )

            return len(validated_rows)
    finally:
        conn.close()

# Routes

@app.route("/", methods=["GET", "POST"])
def intake():
    latest = ""

    # Handle unlock attempt first (works even when currently locked).
    if request.method == "POST" and auth_enabled() and "access_code" in request.form:
        submitted_code = request.form.get("access_code")
        if auth_ok(submitted_code):
            set_authed(True)
        return_to = (request.form.get("return_to") or "").strip()
        if return_to.startswith("/"):
            return redirect(return_to)
        return redirect("/")

    # Determine auth state and enforce timeout for authed sessions.
    authed = enforce_inactivity_timeout()

    # Handle scan / clear only when authed.
    if request.method == "POST" and authed:
        session["equipment_type"] = (request.form.get("equipment_type") or "").strip()
        action = request.form.get("action", "scan")

        if action == "clear":
            SCAN_QUEUE.clear()
            session.pop("holder_id", None)
            touch_session()
        else:
            raw = request.form.get("scan_text", "")
            scan = sanitize_scan(raw)
            if scan:
                equipment_type = (request.form.get("equipment_type") or session.get("equipment_type") or "laptop").strip() or "laptop"
                record = Scan.now(asset_tag=scan, equipment_type=equipment_type)

                existing = {s.asset_tag for s in SCAN_QUEUE}
                if record.asset_tag in existing:
                    return_to = (request.form.get("return_to") or "").strip()
                    if return_to.startswith("/"):
                        return redirect(return_to)
                    return redirect("/")

                SCAN_QUEUE.append(record)
                latest = record.asset_tag
                session["equipment_type"] = "laptop"
                touch_session()

        return_to = (request.form.get("return_to") or "").strip()
        if return_to.startswith("/"):
            return redirect(return_to)
        return redirect("/")

    # View model for template.
    timeout_seconds = INTAKE_TIMEOUT_SECONDS
    last_seen_age_seconds = seconds_since_last_seen()

    # If unlocked/auth-disabled, never allow the UI to show a blank "Last activity".
    if authed and last_seen_age_seconds is None:
        last_seen_age_seconds = 0

    if not SCAN_QUEUE:
        session["equipment_type"] = "laptop"
    return render_template(
        "index.html",
        latest=latest,
        queue=SCAN_QUEUE,
        queue_len=len(SCAN_QUEUE),
        authed=authed,
        auth_enabled=auth_enabled(),
        timeout_seconds=timeout_seconds,
        last_seen_age_seconds=last_seen_age_seconds,
        equipment_type=(session.get("equipment_type") or "laptop").strip() or "laptop",
    )


@app.get("/preview")
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
        stock_out_mode=bool(session.get("stock_out_mode")),
    )


@app.get("/preview/validate")
def preview_validate():
    parsed_rows = build_parsed_rows_from_queue()
    result = validate_rows(parsed_rows)

    return {
        "row_count": len(parsed_rows),
        "valid": bool(result.get("valid")) if isinstance(result, dict) else False,
        "result": result,
    }

@app.post("/preview/mode")
def preview_mode():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    enabled = (request.form.get("stock_out_mode") or "").strip().lower() in {"on", "true", "1", "yes"}
    session["stock_out_mode"] = bool(enabled)

    # If turning off stock-out mode, clear holder selection to avoid confusion.
    if not enabled:
        session.pop("holder_id", None)

    touch_session()
    return redirect(url_for("preview"))

@app.post("/preview/discard")
def preview_discard():
    # Enforce auth and inactivity timeout for discard requests.
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        if wants_json():
            return {"ok": False, "discarded": 0, "error": "Locked"}, 401
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    discarded = len(SCAN_QUEUE)
    SCAN_QUEUE.clear()
    session.pop("holder_id", None)

    # Reset UI defaults back to laptop (same invariant as intake()).
    session["equipment_type"] = "laptop"
    touch_session()

    if wants_json():
        return {"ok": True, "discarded": discarded}

    flash("Batch discarded.", "success")
    return redirect(url_for("intake"))

@app.post("/preview/commit")
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

    stock_out_mode = bool(session.get("stock_out_mode"))

    # Normal intake commit mode

    if not stock_out_mode:
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
        session.pop("holder_id", None)  # keep tidy; holder is only meaningful for stock-out
        touch_session()

        if wants_json():
            return {"ok": True, "committed": result.committed_count}

        flash(f"Added {result.committed_count} items to the database.", "success")
        return redirect(url_for("intake"))

    # Stock-out commit mode

    holder = _selected_holder_from_session()
    if holder is None:
        if wants_json():
            return {
                "ok": False,
                "committed": 0,
                "error": "Select a holder before stock-out.",
            }, 400
        flash("Select a holder before stock-out.", "error")
        return redirect(url_for("preview"))

    asset_tags = _queue_asset_tags()

    try:
        committed_count = _stock_out_batch(asset_tags, holder["id"])
    except ValueError as e:
        if wants_json():
            return {"ok": False, "committed": 0, "error": str(e)}, 400
        flash(f"Stock-out failed: {e}", "error")
        return redirect(url_for("preview"))

    SCAN_QUEUE.clear()
    session.pop("holder_id", None)
    touch_session()

    if wants_json():
        return {"ok": True, "committed": committed_count}

    flash(f"Stocked out {committed_count} items.", "success")
    return redirect(url_for("intake"))


@app.get("/issue/preview")
def issue_preview():
    stock_out_mode = bool(session.get("stock_out_mode"))
    if not stock_out_mode:
        flash("Enable stock-out mode before using Issue Assets.", "error")
        return redirect(url_for("preview"))

    selected_holder = _selected_holder_from_session()
    asset_tags = _queue_asset_tags()
    issue_preview_state = _build_issue_preview_state(asset_tags, selected_holder)

    return render_template(
        "issue_preview.html",
        stock_out_mode=stock_out_mode,
        selected_holder=selected_holder,
        queued_count=len(asset_tags),
        assets=issue_preview_state["assets"],
        ready_count=issue_preview_state["ready_count"],
        blocking_issues=issue_preview_state["blocking_issues"],
    )


@app.post("/issue/commit")
def issue_commit():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Locked"}, 401
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    stock_out_mode = bool(session.get("stock_out_mode"))
    if not stock_out_mode:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Issue mode is not enabled."}, 400
        flash("Enable stock-out mode before issuing assets.", "error")
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
            return {"ok": False, "committed": 0, "error": "Select a holder before stock-out."}, 400
        flash("Select a holder before stock-out.", "error")
        return redirect(url_for("issue_preview"))

    asset_tags = _queue_asset_tags()
    if not asset_tags:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "No assets in the queue to stock out"}, 400
        flash("No assets in the queue to stock out.", "error")
        return redirect(url_for("issue_preview"))

    try:
        committed_count = _stock_out_batch(asset_tags, holder["id"])
    except ValueError as e:
        if wants_json():
            return {"ok": False, "committed": 0, "error": str(e)}, 400
        flash(f"Stock-out failed: {e}", "error")
        return redirect(url_for("issue_preview"))

    SCAN_QUEUE.clear()
    session.pop("holder_id", None)
    touch_session()

    if wants_json():
        return {"ok": True, "committed": committed_count, "error": None}

    flash(f"Issued {committed_count} assets.", "success")
    return redirect(url_for("intake"))


@app.get("/return")
def return_queue():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Locked"}, 401
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    asset_tags = _queue_asset_tags()
    state = _build_return_preview_state(asset_tags)

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
        queued_count=len(asset_tags),
        ready_count=state["ready_count"],
        blocking_issues=state["blocking_issues"],
    )


@app.get("/return/preview")
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
        queued_count=len(asset_tags),
        preview_rows=state["assets"],
        ready_count=state["ready_count"],
        blocking_issues=state["blocking_issues"],
    )


@app.post("/return/commit")
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
        committed_count = _stock_in_batch(asset_tags)
    except ValueError as e:
        if wants_json():
            return {"ok": False, "committed": 0, "error": str(e)}, 400
        flash(f"Return failed: {e}", "error")
        return redirect(url_for("return_preview"))

    SCAN_QUEUE.clear()
    touch_session()

    if wants_json():
        return {"ok": True, "committed": committed_count, "error": None}

    flash(f"Returned {committed_count} assets.", "success")
    return redirect(url_for("return_queue"))

@app.get("/lock")
def lock():
    set_authed(False)
    return redirect("/")

@app.get("/holders")
def holders_search():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    query = (request.args.get("q") or "").strip()
    results = search_holders(query) if query else []

    return render_template(
        "holders_search.html",
        query=query,
        results=results,
        selected_holder=_selected_holder_from_session(),
    )

@app.post("/holders/select")
def holders_select():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    holder_id_raw = (request.form.get("holder_id") or "").strip()
    if not holder_id_raw:
        flash("Select a holder first.", "error")
        return redirect(url_for("holders_search"))

    holder = get_holder(holder_id_raw)
    if holder is None:
        flash("Selected holder not found.", "error")
        return redirect(url_for("holders_search"))

    session["holder_id"] = holder["id"]
    touch_session()
    flash(f"Selected holder: {holder['name']}", "success")
    return redirect(url_for("holders_search"))


@app.post("/holders/clear")
def holders_clear():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    session.pop("holder_id", None)
    touch_session()
    flash("Cleared holder selection.", "success")
    return redirect(url_for("holders_search"))


@app.route("/admin/assets/new", methods=["GET", "POST"])
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
        "assign_now": "no",
        "case_number": "",
        "slot_number": "",
    }
    error_message: Optional[str] = None

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
            "assign_now": "yes" if _is_truthy(request.form.get("assign_now")) else "no",
            "case_number": (request.form.get("case_number") or "").strip().upper(),
            "slot_number": (request.form.get("slot_number") or "").strip(),
        }

        errors: list[str] = []
        if not form_state["asset_tag"]:
            errors.append("asset_tag is required.")
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

        assign_slot_number: Optional[int] = None
        assign_case_number: Optional[str] = None
        if form_state["assign_now"] == "yes":
            if not form_state["case_number"]:
                errors.append("case_number is required when assign_now is enabled.")
            if not form_state["slot_number"]:
                errors.append("slot_number is required when assign_now is enabled.")
            if form_state["slot_number"]:
                try:
                    assign_slot_number = int(form_state["slot_number"])
                except ValueError:
                    errors.append("slot_number must be an integer.")
            assign_case_number = form_state["case_number"] or None

        if errors:
            error_message = "; ".join(errors)
            return render_template("admin_new_asset.html", form=form_state, error_message=error_message)

        conn = get_connection()
        try:
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
                    assign_case_number=assign_case_number,
                    assign_slot_number=assign_slot_number,
                )
                conn.commit()
            except ValueError as e:
                conn.rollback()
                error_message = str(e)
                return render_template("admin_new_asset.html", form=form_state, error_message=error_message)
            except sqlite3.IntegrityError as e:
                conn.rollback()
                error_message = f"create failed: {e}"
                return render_template("admin_new_asset.html", form=form_state, error_message=error_message)
            except Exception:
                conn.rollback()
                raise
        finally:
            conn.close()

        flash(f"Created asset {form_state['asset_tag']}.", "success")
        return redirect(url_for("admin_new_asset"))

    return render_template("admin_new_asset.html", form=form_state, error_message=error_message)


@app.route("/admin/assets/retire", methods=["GET", "POST"])
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


@app.post("/admin/assets/create")
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
