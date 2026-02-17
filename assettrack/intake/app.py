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

import os
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
                if location_type != "STORAGE":
                    not_storage.append(canon_tag)

                if not _is_slotted(conn, canon_tag):
                    not_slotted.append(canon_tag)

            if unknown_tags or not_storage or not_slotted:
                parts: list[str] = []
                if unknown_tags:
                    parts.append(f"Unknown asset_tag(s): {', '.join(unknown_tags)}")
                if not_storage:
                    parts.append(f"Not in STORAGE: {', '.join(not_storage)}")
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

            if unknown_tags or not_in_custody or no_home_slot or occupied_home_slot:
                parts: list[str] = []
                if unknown_tags:
                    parts.append(f"Unknown asset_tag(s): {', '.join(unknown_tags)}")
                if not_in_custody:
                    parts.append(f"Not in IN_CUSTODY: {', '.join(not_in_custody)}")
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


if __name__ == "__main__":
    # Local dev run (and container run).
    app.run(host="0.0.0.0", port=8000, debug=True)
