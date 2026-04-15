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

import hashlib
import json
import os
import re
import sqlite3
import smtplib
import time
from email.message import EmailMessage
from email.utils import getaddresses
from io import BytesIO
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import assettrack.db as db_module
from assettrack.assets import get_asset_table_columns
from assettrack.dashboard import build_dashboard_data, get_custody_days_threshold
from assettrack.db import bootstrap_db, get_connection
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
from assettrack.audit import ACTIVE_EVENTS_WHERE, record_event
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

bootstrap_db(db_module.DB_PATH)

# In-memory only: wiped on restart
SCAN_QUEUE: list[Scan] = []

INTAKE_TIMEOUT_SECONDS = int(os.getenv("ASSETTRACK_INTAKE_TIMEOUT_SECONDS", "300"))  # default 5 min
TERMINAL_LOCATION_TYPE = "DISPOSED"
TERMINAL_LOCATION_TYPES = {"DISPOSED", "RETIRED"}
RETIRE_FAILURE_TYPES = {"HARDWARE", "LOST", "STOLEN", "DESTROYED", "OTHER"}
ASSET_EQUIPMENT_TYPE_OPTIONS = ("laptop", "tablet")
DEMO_SUMMARY = {
    "assets_in_custody": 18,
    "pending_receipts": 2,
    "holders": 7,
    "cases": 4,
}
DEMO_HOLDERS = [
    {"name": "Signal Platoon", "organization": "Operations", "email": "signal.platoon@example.demo", "asset_count": 6},
    {"name": "Maintenance Shop", "organization": "Support", "email": "maintenance.shop@example.demo", "asset_count": 4},
    {"name": "Forward Team Alpha", "organization": "Field Team", "email": "fta@example.demo", "asset_count": 3},
]
DEMO_RECEIPTS = [
    {
        "title": "Issue Receipt - Signal Platoon - Apr 3, 2026",
        "status": "Queued",
        "recipient_email": "signal.platoon@example.demo",
        "receipt_key": "ISSUE-2026-0042",
    },
    {
        "title": "Return Receipt - Maintenance Shop - Apr 2, 2026",
        "status": "Sent",
        "recipient_email": "maintenance.shop@example.demo",
        "receipt_key": "RETURN-2026-0017",
    },
]
DEMO_AUDIT = [
    {"event_date": "2026-04-03T09:14:00Z", "event_type": "ISSUE", "asset_tag": "LT-4421", "actor": "operator-demo"},
    {"event_date": "2026-04-03T09:18:00Z", "event_type": "ISSUE", "asset_tag": "TB-1188", "actor": "operator-demo"},
    {"event_date": "2026-04-02T16:42:00Z", "event_type": "RETURN", "asset_tag": "LT-3010", "actor": "operator-demo"},
]
DEMO_RECEIPT_SEND_LIMIT = 2
DEMO_RECEIPT_COOLDOWN_SECONDS = 30


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


def _prefers_json_error_response() -> bool:
    if request.is_json:
        return True

    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json" and (
        request.accept_mimetypes["application/json"] >= request.accept_mimetypes["text/html"]
    )


@app.errorhandler(404)
def not_found_page(_error):
    if _prefers_json_error_response():
        return {"ok": False, "error": "Not Found"}, 404
    return render_template("404.html"), 404


def sanitize_scan(raw: str) -> str:
    """Keep only letters and numbers; drop tabs/newlines/suffix junk."""
    return "".join(ch for ch in raw if ch.isalnum()).upper()


def _demo_page_context() -> dict[str, object]:
    demo_token = str(request.args.get("token") or "").strip()
    demo_send_enabled = _demo_token_is_valid(demo_token)
    return {
        "summary": DEMO_SUMMARY,
        "holders": DEMO_HOLDERS,
        "receipts": DEMO_RECEIPTS,
        "audit_rows": DEMO_AUDIT,
        "demo_token": demo_token if demo_send_enabled else "",
        "demo_send_enabled": demo_send_enabled,
        "demo_send_limit": DEMO_RECEIPT_SEND_LIMIT,
        "workflow_steps": [
            "Select the holder and confirm prerequisites.",
            "Scan assets into the queue without committing immediately.",
            "Preview the batch before commit so operators can catch mistakes.",
            "Commit once and let receipts track follow-up notification state.",
        ],
    }


def _demo_token_is_valid(submitted_token: object) -> bool:
    configured = str(os.getenv("ASSETTRACK_DEMO_TOKEN") or "").strip()
    provided = str(submitted_token or "").strip()
    return bool(configured) and bool(provided) and provided == configured


def _normalize_demo_email(email: object) -> str:
    normalized = str(email or "").strip().lower()
    if not normalized:
        raise ValueError("Enter an email address.")
    if len(normalized) > 254 or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", normalized):
        raise ValueError("Enter a valid email address.")
    return normalized


def _demo_receipt_send_state() -> dict[str, object]:
    count = int(session.get("demo_receipt_send_count") or 0)
    last_sent_at = str(session.get("demo_receipt_last_sent_at") or "").strip()
    return {
        "count": max(0, count),
        "last_sent_at": last_sent_at,
    }


def _demo_receipt_sample() -> dict[str, object]:
    return {
        "title": "DEMO RECEIPT",
        "subtitle": "Sample receipt only. No operational data.",
        "receipt_key": "DEMO-RECEIPT-0001",
        "commit_at": "2026-04-03T09:18:00Z",
        "holder": "Signal Platoon",
        "organization": "Operations",
        "location": "HQ North / 210",
        "assets": ["LT-4421", "TB-1188"],
    }


def _build_demo_receipt_email_body(sample: dict[str, object]) -> str:
    asset_lines = "\n".join(f"- {asset_tag}" for asset_tag in sample["assets"])
    return (
        f"{sample['title']}\n"
        f"{sample['subtitle']}\n\n"
        f"Receipt key: {sample['receipt_key']}\n"
        f"Recorded at: {sample['commit_at']}\n"
        f"Holder: {sample['holder']}\n"
        f"Organization: {sample['organization']}\n"
        f"Location: {sample['location']}\n"
        f"Assets:\n{asset_lines}\n\n"
        f"---\n"
        f"This is a demo receipt generated by AssetTrack. No operational data.\n"
    )


def _build_demo_receipt_pdf(sample: dict[str, object]) -> bytes:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("DemoReceiptTitle", parent=styles["Heading1"], fontSize=18, leading=21, spaceAfter=6)
    subtitle_style = ParagraphStyle(
        "DemoReceiptSubtitle",
        parent=styles["BodyText"],
        textColor=colors.HexColor("#4f5d6b"),
        spaceAfter=10,
    )
    label_style = ParagraphStyle("DemoReceiptLabel", parent=styles["BodyText"], fontName="Helvetica-Bold", spaceAfter=4)
    body_style = ParagraphStyle("DemoReceiptBody", parent=styles["BodyText"], spaceAfter=4)

    def _text(value: object) -> str:
        return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story: list[object] = [
        Paragraph(_text(sample["title"]), title_style),
        Paragraph(_text(sample["subtitle"]), subtitle_style),
        Paragraph("DEMO ONLY", label_style),
        Paragraph(f"Receipt key: {_text(sample['receipt_key'])}", body_style),
        Paragraph(f"Recorded at: {_text(sample['commit_at'])}", body_style),
        Paragraph(f"Holder: {_text(sample['holder'])}", body_style),
        Paragraph(f"Organization: {_text(sample['organization'])}", body_style),
        Paragraph(f"Location: {_text(sample['location'])}", body_style),
        Spacer(1, 0.12 * inch),
        Paragraph("Assets", label_style),
    ]
    for asset_tag in sample["assets"]:
        story.append(Paragraph(f"- {_text(asset_tag)}", body_style))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title="AssetTrack Demo Receipt",
        author="AssetTrack",
    )

    def _invariant_canvas(*args, **kwargs):
        kwargs.setdefault("invariant", 1)
        return canvas.Canvas(*args, **kwargs)

    doc.build(story, canvasmaker=_invariant_canvas)
    pdf_bytes = buffer.getvalue()
    stable_digest = hashlib.md5(json.dumps(sample, sort_keys=True).encode("utf-8")).hexdigest().encode("ascii")
    return re.sub(
        rb"/ID\s*\[\s*<[^>]+>\s*<[^>]+>\s*\]",
        b"/ID [<" + stable_digest + b"><" + stable_digest + b">]",
        pdf_bytes,
        count=1,
    )


def _send_email_message(message: EmailMessage) -> None:
    smtp_host = str(os.getenv("ASSETTRACK_SMTP_HOST") or "").strip()
    if not smtp_host:
        raise ValueError("Receipt email delivery is not configured.")

    smtp_port = int(str(os.getenv("ASSETTRACK_SMTP_PORT") or "25").strip() or "25")
    smtp_username = str(os.getenv("ASSETTRACK_SMTP_USERNAME") or "").strip()
    smtp_password = str(os.getenv("ASSETTRACK_SMTP_PASSWORD") or "")
    smtp_starttls = str(os.getenv("ASSETTRACK_SMTP_STARTTLS") or "").strip().lower() in {"1", "true", "yes", "on"}
    smtp_use_ssl = str(os.getenv("ASSETTRACK_SMTP_USE_SSL") or "").strip().lower() in {"1", "true", "yes", "on"}

    smtp_cls = smtplib.SMTP_SSL if smtp_use_ssl else smtplib.SMTP
    with smtp_cls(smtp_host, smtp_port, timeout=10) as smtp:
        if smtp_starttls and not smtp_use_ssl:
            smtp.starttls()
        if smtp_username:
            smtp.login(smtp_username, smtp_password)
        smtp.send_message(message)


def _send_demo_receipt_email(recipient_email: str) -> str:
    sample = _demo_receipt_sample()
    from_address = str(os.getenv("ASSETTRACK_RECEIPT_FROM_EMAIL") or "assettrack@local").strip() or "assettrack@local"
    message = EmailMessage()
    message["Subject"] = "DEMO RECEIPT - AssetTrack sample"
    message["From"] = from_address
    message["To"] = recipient_email
    message.set_content(_build_demo_receipt_email_body(sample))
    message.add_attachment(
        _build_demo_receipt_pdf(sample),
        maintype="application",
        subtype="pdf",
        filename="AssetTrack DEMO RECEIPT.pdf",
    )
    _send_email_message(message)
    return recipient_email


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


def _find_return_case_assets_for_scan_tag(conn, scan_tag: str) -> Optional[dict]:
    t = (scan_tag or "").strip()
    if not t:
        return None

    slot_rows = conn.execute(
        """
        SELECT id, case_name, slot_position
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
        asset_rows = conn.execute(
            """
            SELECT asset_tag
            FROM assets
            WHERE home_slot_id = ?
              AND UPPER(COALESCE(location_type, '')) = 'IN_CUSTODY'
            ORDER BY UPPER(asset_tag) ASC, id ASC;
            """,
            (slot_id,),
        ).fetchall()

        for asset_row in asset_rows:
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
    if message == "email is required":
        return "Enter an email address so this holder can receive receipts."
    if message == "email already exists":
        return "A holder with that email already exists."
    if message == "email is invalid":
        return "Enter a valid email address so this holder can receive receipts."
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
    has_asset_tag = bool(asset_tag_clean)
    has_serial_number = bool(serial_clean)

    if not has_asset_tag and not has_serial_number:
        return [], "Enter an asset tag or serial number.", "none"

    if has_asset_tag and has_serial_number:
        lookup_mode = "asset_tag"
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
              AND TRIM(COALESCE(a.serial_number, '')) <> ''
              AND UPPER(a.serial_number) LIKE UPPER(?)
            ORDER BY
                CASE
                    WHEN UPPER(a.asset_tag) = UPPER(?) AND UPPER(a.serial_number) = UPPER(?) THEN 0
                    WHEN UPPER(a.asset_tag) = UPPER(?) THEN 1
                    WHEN UPPER(a.serial_number) = UPPER(?) THEN 2
                    ELSE 3
                END,
                UPPER(a.asset_tag) ASC,
                UPPER(a.serial_number) ASC,
                a.id ASC
            LIMIT 25;
            """,
            (
                f"%{asset_tag_clean}%",
                f"%{serial_clean}%",
                asset_tag_clean,
                serial_clean,
                asset_tag_clean,
                serial_clean,
            ),
        ).fetchall()
        if not rows:
            return [], "Asset not found.", lookup_mode
    elif has_asset_tag:
        lookup_mode = "asset_tag"
        like_pattern = f"%{asset_tag_clean}%"
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
        lookup_mode = "serial_number"
        like_pattern = f"%{serial_clean}%"
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
            SELECT id, asset_tag, location_type, current_holder_id, home_slot_id
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


def _receipt_key(receipt_type: str, source_event_ids: list[int]) -> str:
    return f"{receipt_type}:{'-'.join(str(event_id) for event_id in source_event_ids)}"


def _receipt_holder_snapshot(conn, holder_id: Optional[int]) -> Optional[dict]:
    if holder_id is None:
        return None

    row = conn.execute(
        """
        SELECT id, holder_type, name, organization, organization_id, identifier, email, contact_info
        FROM holders
        WHERE id = ?
        LIMIT 1;
        """,
        (int(holder_id),),
    ).fetchone()
    if row is None:
        return None

    return {
        "id": int(row["id"]),
        "holder_type": str(row["holder_type"] or ""),
        "name": str(row["name"] or ""),
        "organization": str(row["organization"] or ""),
        "organization_id": None if row["organization_id"] is None else int(row["organization_id"]),
        "identifier": str(row["identifier"] or ""),
        "email": str(row["email"] or ""),
        "contact_info": str(row["contact_info"] or ""),
    }


def _receipt_recipient_email(holder_snapshot: object) -> str:
    if not isinstance(holder_snapshot, dict):
        return ""
    return str(holder_snapshot.get("email") or "").strip().lower()


def _receipt_operator_snapshot(conn, user_id: int) -> Optional[dict]:
    row = conn.execute(
        """
        SELECT id, username, role, active
        FROM users
        WHERE id = ?
        LIMIT 1;
        """,
        (int(user_id),),
    ).fetchone()
    if row is None:
        return None

    return {
        "id": int(row["id"]),
        "username": str(row["username"] or ""),
        "role": str(row["role"] or ""),
        "active": bool(int(row["active"] or 0)),
    }


def _receipt_slot_snapshot(conn, slot_id: Optional[int]) -> Optional[dict]:
    if slot_id is None:
        return None

    row = conn.execute(
        """
        SELECT id, case_name, slot_position
        FROM slots
        WHERE id = ?
        LIMIT 1;
        """,
        (int(slot_id),),
    ).fetchone()
    if row is None:
        return None

    return {
        "slot_id": int(row["id"]),
        "case_name": str(row["case_name"] or ""),
        "slot_position": int(row["slot_position"]),
    }


def _receipt_delivery_snapshot(
    *,
    state: str = "pending",
    sent_at: Optional[str] = None,
    last_attempt_at: Optional[str] = None,
    last_error: Optional[str] = None,
) -> dict[str, Optional[str]]:
    normalized_state = str(state or "").strip().lower()
    if normalized_state not in {"pending", "sent", "failed"}:
        normalized_state = "pending"
    return {
        "state": normalized_state,
        "sent_at": sent_at,
        "last_attempt_at": last_attempt_at,
        "last_error": last_error,
    }


def _receipt_delivery_from_row(row: sqlite3.Row, snapshot: dict[str, object]) -> dict[str, Optional[str]]:
    snapshot_delivery = snapshot.get("delivery")
    has_snapshot_delivery = isinstance(snapshot_delivery, dict)
    if not has_snapshot_delivery:
        snapshot_delivery = {}

    sent_at = str(row["sent_at"] or snapshot_delivery.get("sent_at") or "").strip() or None
    last_attempt_at = str(row["last_attempt_at"] or snapshot_delivery.get("last_attempt_at") or "").strip() or None
    last_error = str(row["last_error"] or snapshot_delivery.get("last_error") or "").strip() or None

    if not has_snapshot_delivery and not sent_at and not last_attempt_at and not last_error:
        return {
            "state": None,
            "sent_at": None,
            "last_attempt_at": None,
            "last_error": None,
        }

    if sent_at:
        state = "sent"
    elif last_error:
        state = "failed"
    else:
        state = str(snapshot_delivery.get("state") or "pending").strip().lower() or "pending"

    return _receipt_delivery_snapshot(
        state=state,
        sent_at=sent_at,
        last_attempt_at=last_attempt_at,
        last_error=last_error,
    )


def _receipt_row_snapshot(row: sqlite3.Row) -> dict[str, object]:
    snapshot = json.loads(str(row["snapshot_json"] or "{}"))
    if not isinstance(snapshot, dict):
        snapshot = {}
    return snapshot


def _receipt_queue_row_by_id(conn, receipt_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            id,
            receipt_key,
            receipt_type,
            source_event_ids_json,
            snapshot_json,
            commit_at,
            commit_operator_user_id,
            holder_id,
            sent_at,
            last_attempt_at,
            last_error
        FROM receipt_queue
        WHERE id = ?
        LIMIT 1;
        """,
        (int(receipt_id),),
    ).fetchone()


def _receipt_asset_row_snapshot(conn, asset_tag: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, asset_tag, serial_number, equipment_type, manufacturer, model, model_code, notes, building_room
        FROM assets
        WHERE UPPER(asset_tag) = UPPER(?)
           OR REPLACE(UPPER(asset_tag), '-', '') = UPPER(?)
        LIMIT 1;
        """,
        (asset_tag, asset_tag),
    ).fetchone()


def _receipt_event_rows(conn, source_event_ids: list[int]) -> list[sqlite3.Row]:
    if not source_event_ids:
        raise ValueError("Receipt queue rows require at least one source event.")

    placeholders = ", ".join("?" for _ in source_event_ids)
    rows = conn.execute(
        f"""
        SELECT id, asset_tag, payload, holder_id
        FROM asset_events
        WHERE id IN ({placeholders});
        """,
        tuple(int(event_id) for event_id in source_event_ids),
    ).fetchall()
    rows_by_id = {int(row["id"]): row for row in rows}
    ordered_rows = [rows_by_id[int(event_id)] for event_id in source_event_ids if int(event_id) in rows_by_id]
    if len(ordered_rows) != len(source_event_ids):
        raise ValueError("Receipt queue rows must be derived from stored event history.")
    return ordered_rows


def _receipt_location_context_from_building_room(building_room: str) -> dict[str, str]:
    normalized = str(building_room or "").strip()
    if not normalized:
        return {"building": "", "room": "", "building_room": ""}
    building, separator, room = normalized.partition("/")
    return {
        "building": building,
        "room": room if separator else "",
        "building_room": normalized,
    }


def _build_receipt_snapshot_from_stored_facts(
    conn,
    *,
    receipt_type: str,
    source_event_ids: list[int],
    commit_at: str,
    commit_operator_user_id: int,
) -> dict[str, object]:
    event_rows = _receipt_event_rows(conn, source_event_ids)
    commit_operator_snapshot = _receipt_operator_snapshot(conn, commit_operator_user_id)
    asset_snapshots: list[dict[str, object]] = []

    if receipt_type == "ISSUE":
        holder_ids = {
            int(row["holder_id"])
            for row in event_rows
            if row["holder_id"] is not None
        }
        batch_holder_id = next(iter(holder_ids)) if len(holder_ids) == 1 else None
        batch_holder_snapshot = _receipt_holder_snapshot(conn, batch_holder_id)
        first_payload: dict[str, object] = {}

        for event_row in event_rows:
            payload = json.loads(str(event_row["payload"] or "{}"))
            if not isinstance(payload, dict):
                payload = {}
            if not first_payload:
                first_payload = payload

            asset_tag = str(event_row["asset_tag"] or "").strip()
            asset_row = _receipt_asset_row_snapshot(conn, asset_tag)
            holder_id = None if event_row["holder_id"] is None else int(event_row["holder_id"])
            home_slot_id = payload.get("home_slot_id")
            asset_snapshots.append(
                {
                    "asset_id": None if asset_row is None else int(asset_row["id"]),
                    "asset_tag": str(asset_row["asset_tag"] if asset_row is not None else asset_tag),
                    "serial_number": "" if asset_row is None else str(asset_row["serial_number"] or ""),
                    "equipment_type": "" if asset_row is None else str(asset_row["equipment_type"] or ""),
                    "manufacturer": "" if asset_row is None else str(asset_row["manufacturer"] or ""),
                    "model": "" if asset_row is None else str(asset_row["model"] or ""),
                    "model_code": "" if asset_row is None else str(asset_row["model_code"] or ""),
                    "notes": "" if asset_row is None else str(asset_row["notes"] or ""),
                    "from_location_type": str(payload.get("from_location_type") or ""),
                    "to_location_type": str(payload.get("to_location_type") or ""),
                    "from_building_room": str(payload.get("from_building_room") or ""),
                    "to_building_room": str(payload.get("to_building_room") or ""),
                    "holder_id": holder_id,
                    "holder_snapshot": _receipt_holder_snapshot(conn, holder_id),
                    "home_slot": _receipt_slot_snapshot(
                        conn,
                        int(home_slot_id) if home_slot_id is not None else None,
                    ),
                }
            )

        location_context = _receipt_location_context_from_building_room(str(first_payload.get("to_building_room") or ""))
        return {
            "receipt_type": "ISSUE",
            "commit_at": commit_at,
            "commit_operator_user_id": int(commit_operator_user_id),
            "commit_operator": commit_operator_snapshot,
            "holder_id": batch_holder_id,
            "holder_snapshot": batch_holder_snapshot,
            "recipient_email": _receipt_recipient_email(batch_holder_snapshot),
            "organization_snapshot": None if batch_holder_snapshot is None else {
                "organization": str(batch_holder_snapshot.get("organization") or ""),
                "organization_id": batch_holder_snapshot.get("organization_id"),
            },
            "acknowledgment": (
                dict(first_payload.get("responsibility_ack"))
                if isinstance(first_payload.get("responsibility_ack"), dict)
                else None
            ),
            "location_context": location_context,
            "assets": asset_snapshots,
            "source_event_ids": list(source_event_ids),
            "delivery": _receipt_delivery_snapshot(),
        }

    if receipt_type != "RETURN":
        raise ValueError(f"Unsupported receipt type: {receipt_type}")

    holder_ids: set[int] = set()
    top_level_ack: Optional[dict[str, object]] = None

    for event_row in event_rows:
        payload = json.loads(str(event_row["payload"] or "{}"))
        if not isinstance(payload, dict):
            payload = {}
        responsibility_ack = payload.get("responsibility_ack")
        if not isinstance(responsibility_ack, dict):
            responsibility_ack = {}
        if top_level_ack is None:
            top_level_ack = dict(responsibility_ack)

        from_holder_id = responsibility_ack.get("ack_holder_id")
        normalized_holder_id = int(from_holder_id) if from_holder_id is not None else None
        if normalized_holder_id is not None:
            holder_ids.add(normalized_holder_id)

        asset_tag = str(event_row["asset_tag"] or "").strip()
        asset_row = _receipt_asset_row_snapshot(conn, asset_tag)
        home_slot_id = payload.get("home_slot_id")
        building_room = "" if asset_row is None else str(asset_row["building_room"] or "")
        asset_snapshots.append(
            {
                "asset_id": None if asset_row is None else int(asset_row["id"]),
                "asset_tag": str(asset_row["asset_tag"] if asset_row is not None else asset_tag),
                "serial_number": "" if asset_row is None else str(asset_row["serial_number"] or ""),
                "equipment_type": "" if asset_row is None else str(asset_row["equipment_type"] or ""),
                "manufacturer": "" if asset_row is None else str(asset_row["manufacturer"] or ""),
                "model": "" if asset_row is None else str(asset_row["model"] or ""),
                "model_code": "" if asset_row is None else str(asset_row["model_code"] or ""),
                "notes": "" if asset_row is None else str(asset_row["notes"] or ""),
                "from_location_type": str(payload.get("from_location_type") or ""),
                "to_location_type": str(payload.get("to_location_type") or ""),
                "from_holder_id": normalized_holder_id,
                "from_holder_snapshot": _receipt_holder_snapshot(conn, normalized_holder_id),
                "to_holder_id": None,
                "from_building_room": building_room,
                "to_building_room": building_room,
                "home_slot": _receipt_slot_snapshot(
                    conn,
                    int(home_slot_id) if home_slot_id is not None else None,
                ),
            }
        )

    batch_holder_id = next(iter(holder_ids)) if len(holder_ids) == 1 else None
    batch_holder_snapshot = _receipt_holder_snapshot(conn, batch_holder_id)
    if top_level_ack is not None and len(holder_ids) != 1:
        top_level_ack.pop("ack_holder_id", None)

    return {
        "receipt_type": "RETURN",
        "commit_at": commit_at,
        "commit_operator_user_id": int(commit_operator_user_id),
        "commit_operator": commit_operator_snapshot,
        "holder_id": batch_holder_id,
        "holder_snapshot": batch_holder_snapshot,
        "recipient_email": _receipt_recipient_email(batch_holder_snapshot),
        "organization_snapshot": None if batch_holder_snapshot is None else {
            "organization": str(batch_holder_snapshot.get("organization") or ""),
            "organization_id": batch_holder_snapshot.get("organization_id"),
        },
        "acknowledgment": top_level_ack,
        "assets": asset_snapshots,
        "source_event_ids": list(source_event_ids),
        "delivery": _receipt_delivery_snapshot(),
    }


def _insert_receipt_queue_row(
    conn,
    *,
    receipt_type: str,
    source_event_ids: list[int],
    snapshot: dict[str, object],
    commit_at: str,
    commit_operator_user_id: int,
    holder_id: Optional[int],
) -> int:
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO receipt_queue (
            receipt_key,
            receipt_type,
            source_event_ids_json,
            snapshot_json,
            commit_at,
            commit_operator_user_id,
            holder_id,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            _receipt_key(receipt_type, source_event_ids),
            receipt_type,
            json.dumps(source_event_ids),
            json.dumps(snapshot, sort_keys=True),
            commit_at,
            int(commit_operator_user_id),
            None if holder_id is None else int(holder_id),
            now_iso,
            now_iso,
        ),
    )
    return int(cursor.lastrowid)


def _issue_batch(
    asset_tags: list[str],
    holder_id: int,
    issue_location: dict[str, str],
    responsibility_ack: dict[str, object],
    *,
    commit_operator_user_id: int,
) -> tuple[int, int]:
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
            event_ids: list[int] = []

            for asset_id, canon_tag, home_slot_id in canon_assets:
                asset_row = conn.execute(
                    """
                    SELECT serial_number, equipment_type, manufacturer, model, model_code, notes, building_room
                    FROM assets
                    WHERE id = ?
                    LIMIT 1;
                    """,
                    (asset_id,),
                ).fetchone()
                previous_building_room = "" if asset_row is None else str(asset_row["building_room"] or "").strip()
                home_slot_snapshot = _receipt_slot_snapshot(conn, home_slot_id)

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

                event_cursor = conn.execute(
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
                                "responsibility_ack": responsibility_ack,
                            }
                        ),
                        holder_id,
                    ),
                )
                event_ids.append(int(event_cursor.lastrowid))
            snapshot = _build_receipt_snapshot_from_stored_facts(
                conn,
                receipt_type="ISSUE",
                source_event_ids=event_ids,
                commit_at=now_iso,
                commit_operator_user_id=commit_operator_user_id,
            )
            receipt_id = _insert_receipt_queue_row(
                conn,
                receipt_type="ISSUE",
                source_event_ids=event_ids,
                snapshot=snapshot,
                commit_at=now_iso,
                commit_operator_user_id=commit_operator_user_id,
                holder_id=holder_id,
            )

            return len(canon_assets), receipt_id
    finally:
        conn.close()


def _return_batch(
    asset_tags: list[str],
    responsibility_ack: dict[str, object],
    *,
    commit_operator_user_id: int,
) -> tuple[int, int]:
    if not asset_tags:
        raise ValueError("No assets in the queue to return")

    def _canon_asset_row_for_scan_tag(conn, scan_tag: str) -> Optional[dict]:
        t = (scan_tag or "").strip()
        if not t:
            return None

        rows = conn.execute(
            """
            SELECT id, asset_tag, location_type, current_holder_id, home_slot_id
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

                validated_rows.append(
                    {
                        "asset_id": int(asset_row["id"]),
                        "asset_tag": canon_tag,
                        "home_slot_id": int(slot["id"]),
                        "current_holder_id": None if asset_row["current_holder_id"] is None else int(asset_row["current_holder_id"]),
                    }
                )

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
            event_ids: list[int] = []

            for row in validated_rows:
                asset_id = row["asset_id"]
                canon_tag = row["asset_tag"]
                home_slot_id = row["home_slot_id"]
                current_holder_id = row["current_holder_id"]

                conn.execute(
                    """
                    UPDATE assets
                    SET location_type = ?, current_holder_id = NULL
                    WHERE UPPER(asset_tag) = UPPER(?)
                       OR REPLACE(UPPER(asset_tag), '-', '') = UPPER(?);
                    """,
                    ("STORAGE", canon_tag, canon_tag),
                )

                conn.execute(
                    """
                    INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
                    VALUES (?, ?, ?);
                    """,
                    (home_slot_id, asset_id, now_iso),
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

                event_cursor = conn.execute(
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
                        RETURN_EVENT_TYPE,
                        now_iso,
                        "system",
                        None,
                        json.dumps(
                            {
                                "from_location_type": "IN_CUSTODY",
                                "to_location_type": "STORAGE",
                                "home_slot_id": home_slot_id,
                                "responsibility_ack": {
                                    **responsibility_ack,
                                    "ack_holder_id": current_holder_id,
                                },
                            }
                        ),
                        None,
                    ),
                )
                event_ids.append(int(event_cursor.lastrowid))
            snapshot = _build_receipt_snapshot_from_stored_facts(
                conn,
                receipt_type="RETURN",
                source_event_ids=event_ids,
                commit_at=now_iso,
                commit_operator_user_id=commit_operator_user_id,
            )
            receipt_id = _insert_receipt_queue_row(
                conn,
                receipt_type="RETURN",
                source_event_ids=event_ids,
                snapshot=snapshot,
                commit_at=now_iso,
                commit_operator_user_id=commit_operator_user_id,
                holder_id=snapshot.get("holder_id"),
            )

            return len(validated_rows), receipt_id
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
                    if return_to_path in {"/issue", "/return"}:
                        try:
                            if return_to_path == "/issue":
                                case_match = _find_case_assets_for_scan_tag(conn, value)
                            else:
                                case_match = _find_return_case_assets_for_scan_tag(conn, value)
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


@app.get("/demo")
def demo():
    return render_template("demo.html", **_demo_page_context())


@app.post("/demo/send-sample-receipt")
def demo_send_sample_receipt():
    token = str(request.form.get("token") or request.args.get("token") or "").strip()
    if not _demo_token_is_valid(token):
        abort(404)

    send_state = _demo_receipt_send_state()
    if int(send_state["count"]) >= DEMO_RECEIPT_SEND_LIMIT:
        flash("Demo send limit reached for this session.", "error")
        return redirect(url_for("demo", token=token))

    now_utc = datetime.now(timezone.utc)
    last_sent_at = str(send_state["last_sent_at"] or "").strip()
    if last_sent_at:
        try:
            last_sent_dt = datetime.fromisoformat(last_sent_at)
        except ValueError:
            last_sent_dt = None
        if last_sent_dt is not None and (now_utc - last_sent_dt).total_seconds() < DEMO_RECEIPT_COOLDOWN_SECONDS:
            flash("Please wait before sending another sample receipt.", "error")
            return redirect(url_for("demo", token=token))

    try:
        recipient_email = _normalize_demo_email(request.form.get("email"))
        sent_to = _send_demo_receipt_email(recipient_email)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("demo", token=token))
    except Exception as exc:
        flash(f"Demo receipt email failed: {exc}", "error")
        return redirect(url_for("demo", token=token))

    session["demo_receipt_send_count"] = int(send_state["count"]) + 1
    session["demo_receipt_last_sent_at"] = now_utc.isoformat()
    touch_session()
    flash(f"Demo receipt sent to {sent_to}.", "success")
    return redirect(url_for("demo", token=token))


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
    user = current_user()
    if user is None:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Authenticated operator not found."}, 400
        flash("Authenticated operator not found.", "error")
        return redirect(url_for("preview"))
    responsibility_ack = {
        "acknowledged": True,
        "ack_holder_id": int(holder["id"]),
        "ack_operator_user_id": int(user["id"]),
        "ack_at": datetime.now(timezone.utc).isoformat(),
        "ack_scope": "batch",
    }

    try:
        committed_count, receipt_id = _issue_batch(
            asset_tags,
            holder["id"],
            issue_location_form,
            responsibility_ack,
            commit_operator_user_id=int(user["id"]),
        )
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

    acknowledged = (request.form.get("confirm_responsibility_ack") or "").strip().lower() in {"on", "true", "1", "yes"}
    if not acknowledged:
        if wants_json():
            return {
                "ok": False,
                "committed": 0,
                "error": "Confirm responsibility acknowledgment before issuing assets.",
            }, 400
        flash("Confirm responsibility acknowledgment before issuing assets.", "error")
        preview_response = issue_preview()
        return preview_response, 400

    holder = _selected_holder_from_session()
    if holder is None:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Select a holder before issuing assets."}, 400
        flash("Select a holder before issuing assets.", "error")
        return redirect(url_for("issue_preview"))

    user = current_user()
    if user is None:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Authenticated operator not found."}, 400
        flash("Authenticated operator not found.", "error")
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

    responsibility_ack = {
        "acknowledged": True,
        "ack_holder_id": int(holder["id"]),
        "ack_operator_user_id": int(user["id"]),
        "ack_at": datetime.now(timezone.utc).isoformat(),
        "ack_scope": "batch",
    }

    try:
        committed_count, receipt_id = _issue_batch(
            asset_tags,
            holder["id"],
            issue_location_form,
            responsibility_ack,
            commit_operator_user_id=int(user["id"]),
        )
    except ValueError as e:
        if wants_json():
            return {"ok": False, "committed": 0, "error": str(e)}, 400
        flash(f"Issue failed: {e}", "error")
        return redirect(url_for("issue_preview"))

    SCAN_QUEUE.clear()
    touch_session()

    if wants_json():
        return {"ok": True, "committed": committed_count, "receipt_id": receipt_id, "error": None}

    flash(f"Issued {committed_count} assets.", "success")
    return redirect(url_for("receipt_detail", receipt_id=receipt_id))


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

    acknowledged = (request.form.get("confirm_responsibility_ack") or "").strip().lower() in {"on", "true", "1", "yes"}
    if not acknowledged:
        if wants_json():
            return {
                "ok": False,
                "committed": 0,
                "error": "Confirm responsibility acknowledgment before returning assets.",
            }, 400
        flash("Confirm responsibility acknowledgment before returning assets.", "error")
        return redirect(url_for("return_preview"))

    asset_tags = _queue_asset_tags()
    state = _build_return_preview_state(asset_tags)
    if state["blocking_issues"]:
        message = "; ".join(state["blocking_issues"])
        if wants_json():
            return {"ok": False, "committed": 0, "error": message}, 400
        flash(f"Return failed: {message}", "error")
        return redirect(url_for("return_preview"))

    user = current_user()
    if user is None:
        if wants_json():
            return {"ok": False, "committed": 0, "error": "Authenticated operator not found."}, 400
        flash("Authenticated operator not found.", "error")
        return redirect(url_for("return_preview"))

    responsibility_ack = {
        "acknowledged": True,
        "ack_operator_user_id": int(user["id"]),
        "ack_at": datetime.now(timezone.utc).isoformat(),
        "ack_scope": "batch",
    }

    try:
        committed_count, receipt_id = _return_batch(
            asset_tags,
            responsibility_ack,
            commit_operator_user_id=int(user["id"]),
        )
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
        return {"ok": True, "committed": committed_count, "receipt_id": receipt_id, "error": None}

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
    return redirect(url_for("receipt_detail", receipt_id=receipt_id))

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


@app.get("/receipts/<int:receipt_id>")
@require_login
def receipt_detail(receipt_id: int):
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                id,
                receipt_key,
                receipt_type,
                source_event_ids_json,
                snapshot_json,
                commit_at,
                commit_operator_user_id,
                holder_id,
                sent_at,
                last_attempt_at,
                last_error
            FROM receipt_queue
            WHERE id = ?
            LIMIT 1;
            """,
            (receipt_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        abort(404)

    receipt = _receipt_from_queue_row(row)

    return render_template(
        "receipt_detail.html",
        receipt=receipt,
    )


def _receipt_from_queue_row(row: sqlite3.Row) -> dict[str, object]:
    source_event_ids = json.loads(str(row["source_event_ids_json"] or "[]"))
    if not isinstance(source_event_ids, list):
        source_event_ids = []

    snapshot = json.loads(str(row["snapshot_json"] or "{}"))
    if not isinstance(snapshot, dict):
        snapshot = {}

    snapshot_assets = snapshot.get("assets")
    assets = snapshot_assets if isinstance(snapshot_assets, list) else []
    holder_snapshot = snapshot.get("holder_snapshot")
    if not isinstance(holder_snapshot, dict):
        holder_snapshot = None
    location_context = snapshot.get("location_context")
    if not isinstance(location_context, dict):
        location_context = None
    acknowledgment = snapshot.get("acknowledgment")
    if not isinstance(acknowledgment, dict):
        acknowledgment = None

    snapshot_receipt_type = str(snapshot.get("receipt_type") or "").strip().upper()
    row_receipt_type = str(row["receipt_type"] or "").strip().upper()
    receipt_type = snapshot_receipt_type or row_receipt_type

    snapshot_commit_at = str(snapshot.get("commit_at") or "").strip()
    commit_at = snapshot_commit_at or str(row["commit_at"] or "")
    delivery = _receipt_delivery_from_row(row, snapshot)

    snapshot_operator_id = snapshot.get("commit_operator_user_id")
    commit_operator_user_id = (
        int(snapshot_operator_id)
        if snapshot_operator_id is not None
        else int(row["commit_operator_user_id"])
    )
    holder_display_name = _receipt_display_holder_name(
        holder_snapshot,
        holder_id=snapshot.get("holder_id") if snapshot.get("holder_id") is not None else row["holder_id"],
        receipt_type=receipt_type,
        assets=assets,
    )
    display_date = _receipt_display_date(commit_at)
    delivery_display = {
        "sent_at": _receipt_display_timestamp(delivery.get("sent_at")),
        "last_attempt_at": _receipt_display_timestamp(delivery.get("last_attempt_at")),
    }

    return {
        "id": int(row["id"]),
        "receipt_key": str(row["receipt_key"] or ""),
        "receipt_type": receipt_type,
        "receipt_type_label": _receipt_type_label(receipt_type),
        "holder_display_name": holder_display_name,
        "commit_at": commit_at,
        "commit_at_display": _receipt_display_timestamp(commit_at),
        "display_date": display_date,
        "display_title": _receipt_display_title(receipt_type, holder_display_name, display_date),
        "commit_operator_user_id": commit_operator_user_id,
        "commit_operator": snapshot.get("commit_operator") if isinstance(snapshot.get("commit_operator"), dict) else None,
        "holder_id": snapshot.get("holder_id") if snapshot.get("holder_id") is not None else row["holder_id"],
        "holder_snapshot": holder_snapshot,
        "recipient_email": str(snapshot.get("recipient_email") or "").strip().lower(),
        "organization_snapshot": (
            snapshot.get("organization_snapshot") if isinstance(snapshot.get("organization_snapshot"), dict) else None
        ),
        "delivery": delivery,
        "delivery_display": delivery_display,
        "acknowledgment": acknowledgment,
        "location_context": location_context,
        "assets": assets,
        "source_event_ids": source_event_ids,
    }


def _receipt_summary_from_row(
    row: sqlite3.Row,
    asset_tag_filter: str = "",
    holder_name_filter: str = "",
    building_room_filter: str = "",
) -> dict[str, object]:
    snapshot = json.loads(str(row["snapshot_json"] or "{}"))
    if not isinstance(snapshot, dict):
        snapshot = {}

    assets = snapshot.get("assets")
    asset_list = assets if isinstance(assets, list) else []
    operator = snapshot.get("commit_operator") if isinstance(snapshot.get("commit_operator"), dict) else None
    holder_snapshot = snapshot.get("holder_snapshot") if isinstance(snapshot.get("holder_snapshot"), dict) else None
    organization_snapshot = (
        snapshot.get("organization_snapshot") if isinstance(snapshot.get("organization_snapshot"), dict) else None
    )
    location_context = snapshot.get("location_context") if isinstance(snapshot.get("location_context"), dict) else None

    receipt_type = str(snapshot.get("receipt_type") or row["receipt_type"] or "").strip().upper()
    commit_at = str(snapshot.get("commit_at") or row["commit_at"] or "")
    holder_id = snapshot.get("holder_id") if snapshot.get("holder_id") is not None else row["holder_id"]
    delivery = _receipt_delivery_from_row(row, snapshot)

    if holder_snapshot and str(holder_snapshot.get("name") or "").strip():
        holder_summary = str(holder_snapshot.get("name") or "").strip()
    elif holder_id is not None:
        holder_summary = f"holder_id {holder_id}"
    elif receipt_type == "RETURN" and len(asset_list) > 1:
        holder_summary = "Multiple holders"
    else:
        holder_summary = "Unknown"

    if organization_snapshot and str(organization_snapshot.get("organization") or "").strip():
        organization_summary = str(organization_snapshot.get("organization") or "").strip()
    else:
        organization_summary = ""

    if location_context and str(location_context.get("building_room") or "").strip():
        location_summary = str(location_context.get("building_room") or "").strip()
    elif receipt_type == "RETURN":
        location_summary = "Return location varies by asset"
    else:
        location_summary = "Unknown"

    if operator and str(operator.get("username") or "").strip():
        committed_by = str(operator.get("username") or "").strip()
    else:
        committed_by = f"user_id {int(row['commit_operator_user_id'])}"

    display_date = _receipt_display_date(commit_at)
    display_holder_name = _receipt_display_holder_name(
        holder_snapshot,
        holder_id=holder_id,
        receipt_type=receipt_type,
        assets=asset_list,
    )

    try:
        commit_at_display = datetime.fromisoformat(commit_at).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        commit_at_display = commit_at or "Unknown"

    def _append_unique(values: list[str], value: object) -> None:
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)

    normalized_asset_tag_filter = asset_tag_filter.strip().upper()
    normalized_holder_name_filter = holder_name_filter.strip().upper()
    normalized_building_room_filter = building_room_filter.strip().upper()
    matched_asset_tags: list[str] = []
    asset_tags: list[str] = []
    matched_holder_names: list[str] = []
    matched_locations: list[str] = []
    if normalized_asset_tag_filter:
        for asset in asset_list:
            if not isinstance(asset, dict):
                continue
            asset_tag = str(asset.get("asset_tag") or "").strip()
            if asset_tag and normalized_asset_tag_filter in asset_tag.upper():
                _append_unique(matched_asset_tags, asset_tag)

    if normalized_holder_name_filter:
        if holder_summary != "Unknown" and normalized_holder_name_filter in holder_summary.upper():
            _append_unique(matched_holder_names, holder_summary)
        for asset in asset_list:
            if not isinstance(asset, dict):
                continue
            _append_unique(
                matched_holder_names,
                asset.get("holder_snapshot", {}).get("name") if isinstance(asset.get("holder_snapshot"), dict) else "",
            )
            _append_unique(
                matched_holder_names,
                asset.get("from_holder_snapshot", {}).get("name")
                if isinstance(asset.get("from_holder_snapshot"), dict)
                else "",
            )
        matched_holder_names = [
            value for value in matched_holder_names if normalized_holder_name_filter in value.upper()
        ]

    if normalized_building_room_filter:
        _append_unique(matched_locations, location_summary if location_summary != "Unknown" else "")
        for asset in asset_list:
            if not isinstance(asset, dict):
                continue
            _append_unique(matched_locations, asset.get("from_building_room"))
            _append_unique(matched_locations, asset.get("to_building_room"))
        matched_locations = [value for value in matched_locations if normalized_building_room_filter in value.upper()]

    for asset in asset_list:
        if not isinstance(asset, dict):
            continue
        asset_tag = str(asset.get("asset_tag") or "").strip()
        if asset_tag:
            _append_unique(asset_tags, asset_tag)

    visible_asset_tags = matched_asset_tags or asset_tags[:1]
    additional_asset_tag_count = max(len(asset_tags) - len(visible_asset_tags), 0)

    return {
        "id": int(row["id"]),
        "receipt_key": str(row["receipt_key"] or ""),
        "receipt_type": receipt_type,
        "receipt_type_label": _receipt_type_label(receipt_type),
        "display_title": _receipt_display_title(receipt_type, display_holder_name, display_date),
        "display_date": display_date,
        "delivery_state": delivery.get("state"),
        "commit_at": commit_at,
        "commit_at_display": commit_at_display,
        "committed_by": committed_by,
        "holder_summary": holder_summary,
        "holder_display_name": display_holder_name,
        "organization_summary": organization_summary,
        "location_summary": location_summary,
        "asset_count": len(asset_list),
        "visible_asset_tags": visible_asset_tags,
        "additional_asset_tag_count": additional_asset_tag_count,
        "matched_asset_tags": matched_asset_tags,
        "matched_holder_names": matched_holder_names,
        "matched_locations": matched_locations,
    }


def _receipt_type_label(receipt_type: str) -> str:
    normalized = str(receipt_type or "").strip().upper()
    if normalized == "ISSUE":
        return "Issue Receipt"
    if normalized == "RETURN":
        return "Return Receipt"
    return "Receipt"


def _receipt_display_date(commit_at: str) -> str:
    value = str(commit_at or "").strip()
    if not value:
        return "Unknown Date"

    parsed = _parse_display_timestamp(value)
    if parsed is None:
        return value

    month = parsed.strftime("%b")
    day = parsed.day
    year = parsed.year
    return f"{month} {day}, {year}"


def _parse_display_timestamp(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None

    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _receipt_display_timestamp(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    parsed = _parse_display_timestamp(text)
    if parsed is None:
        return text

    month = parsed.strftime("%b")
    day = parsed.day
    year = parsed.year
    return f"{month} {day}, {year} at {parsed.strftime('%H:%M')} UTC"


def _receipt_display_holder_name(
    holder_snapshot: Optional[dict[str, object]],
    *,
    holder_id: object,
    receipt_type: str,
    assets: list[object],
) -> str:
    if isinstance(holder_snapshot, dict):
        holder_name = str(holder_snapshot.get("name") or "").strip()
        if holder_name:
            return holder_name

    unique_names: list[str] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        for field_name in ("holder_snapshot", "from_holder_snapshot"):
            snapshot = asset.get(field_name)
            if not isinstance(snapshot, dict):
                continue
            holder_name = str(snapshot.get("name") or "").strip()
            if holder_name and holder_name not in unique_names:
                unique_names.append(holder_name)

    if len(unique_names) == 1:
        return unique_names[0]
    if len(unique_names) > 1:
        return "Multiple Holders"
    if holder_id is not None:
        return f"Holder {holder_id}"
    if str(receipt_type or "").strip().upper() == "RETURN":
        return "Returning Holder"
    return "Unknown Holder"


def _receipt_display_title(receipt_type: str, holder_name: str, display_date: str) -> str:
    return f"{_receipt_type_label(receipt_type)} — {holder_name or 'Unknown Holder'} — {display_date or 'Unknown Date'}"


def _receipt_email_recipients(receipt: dict[str, object]) -> list[str]:
    recipient_email = str(receipt.get("recipient_email") or "").strip().lower()
    return _normalized_email_addresses(recipient_email)


def _receipt_cc_recipients() -> list[str]:
    configured_cc = str(os.getenv("ASSETTRACK_RECEIPT_CC_EMAIL") or "").strip().lower()
    return _normalized_email_addresses(configured_cc)


def _normalized_email_addresses(raw_addresses: str) -> list[str]:
    if not raw_addresses:
        return []

    recipients: list[str] = []
    for _, email_address in getaddresses([raw_addresses]):
        normalized = str(email_address or "").strip().lower()
        if normalized and normalized not in recipients:
            recipients.append(normalized)

    return recipients


def _receipt_pdf_download_name(receipt: dict[str, object]) -> str:
    title = str(receipt.get("display_title") or "").strip() or "Receipt"
    sanitized = title.replace(" — ", " - ")
    sanitized = re.sub(r'[<>:"/\\|?*]', " ", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip().rstrip(". ")
    return f"{sanitized or 'Receipt'}.pdf"


def _build_receipt_email_body(receipt: dict[str, object]) -> str:
    asset_tags: list[str] = []
    for asset in receipt.get("assets", []):
        if not isinstance(asset, dict):
            continue
        asset_tag = str(asset.get("asset_tag") or "").strip()
        if asset_tag:
            asset_tags.append(asset_tag)

    asset_lines = "\n".join(f"- {asset_tag}" for asset_tag in asset_tags) or "- None recorded"
    return (
        f"{receipt.get('display_title')}\n\n"
        f"Receipt key: {receipt.get('receipt_key')}\n"
        f"Committed at: {receipt.get('commit_at')}\n"
        f"Holder: {receipt.get('holder_display_name')}\n"
        f"Assets:\n{asset_lines}\n"
    )


def _send_receipt_email(receipt: dict[str, object]) -> list[str]:
    recipients = _receipt_email_recipients(receipt)
    if not recipients:
        raise ValueError("Receipt has no stored email recipient.")
    cc_recipients = _receipt_cc_recipients()
    from_address = str(os.getenv("ASSETTRACK_RECEIPT_FROM_EMAIL") or "assettrack@local").strip() or "assettrack@local"

    message = EmailMessage()
    message["Subject"] = str(receipt.get("display_title") or "AssetTrack Receipt")
    message["From"] = from_address
    message["To"] = ", ".join(recipients)
    if cc_recipients:
        message["Cc"] = ", ".join(cc_recipients)
    message.set_content(_build_receipt_email_body(receipt))
    message.add_attachment(
        _build_receipt_pdf(receipt, for_email=True),
        maintype="application",
        subtype="pdf",
        filename=_receipt_pdf_download_name(receipt),
    )
    _send_email_message(message)

    return recipients


def _receipt_pdf_ack_name(receipt: dict[str, object]) -> str:
    holder_snapshot = receipt.get("holder_snapshot")
    if isinstance(holder_snapshot, dict):
        holder_name = str(holder_snapshot.get("name") or "").strip()
        if holder_name:
            return holder_name

    names: list[str] = []
    for asset in receipt.get("assets", []):
        if not isinstance(asset, dict):
            continue
        for field_name in ("holder_snapshot", "from_holder_snapshot"):
            snapshot = asset.get(field_name)
            if not isinstance(snapshot, dict):
                continue
            holder_name = str(snapshot.get("name") or "").strip()
            if holder_name and holder_name not in names:
                names.append(holder_name)

    if names:
        return ", ".join(names)

    return "Unknown"


def _receipt_pdf_initials(name: str) -> str:
    parts = [part for part in name.replace(",", " ").split() if part]
    initials = "".join(part[0].upper() for part in parts[:4] if part and part[0].isalnum())
    return initials or "N/A"


def _receipt_pdf_location_summary(receipt: dict[str, object]) -> str:
    location_context = receipt.get("location_context")
    if isinstance(location_context, dict):
        building_room = str(location_context.get("building_room") or "").strip()
        if building_room:
            return building_room
        building = str(location_context.get("building") or "").strip()
        room = str(location_context.get("room") or "").strip()
        if building and room:
            return f"{building}/{room}"
        if building or room:
            return building or room

    locations: list[str] = []
    for asset in receipt.get("assets", []):
        if not isinstance(asset, dict):
            continue
        for field_name in ("to_building_room", "from_building_room"):
            location = str(asset.get(field_name) or "").strip()
            if location and location not in locations:
                locations.append(location)

    if locations:
        return ", ".join(locations)

    return "Unknown"


def _receipt_acknowledgment_statement(receipt_type: str) -> str:
    if receipt_type == "RETURN":
        return "Custody return was reviewed and confirmed from the stored receipt record."
    return "Custody issue was reviewed and confirmed from the stored receipt record."


def _receipt_pdf_location_type_label(value: object) -> str:
    return str(value or "").strip().replace("_", " ")


def _build_receipt_pdf(receipt: dict[str, object], *, for_email: bool = False) -> bytes:
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    heading = styles["Heading2"]
    title = styles["Title"]
    hero = ParagraphStyle(
        "ReceiptPdfHero",
        parent=styles["Heading1"],
        fontSize=16,
        leading=19,
        spaceAfter=4,
    )
    status = ParagraphStyle(
        "ReceiptPdfStatus",
        parent=body,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#335c81"),
        spaceAfter=4,
    )
    supporting = ParagraphStyle(
        "ReceiptPdfSupporting",
        parent=body,
        textColor=colors.HexColor("#4f5d6b"),
        spaceAfter=4,
    )
    table_body = ParagraphStyle(
        "ReceiptPdfTableBody",
        parent=body,
        fontSize=8.5,
        leading=10,
        splitLongWords=False,
        wordWrap="LTR",
    )
    table_header = ParagraphStyle(
        "ReceiptPdfTableHeader",
        parent=table_body,
        fontName="Helvetica-Bold",
    )

    def _text(value: object) -> str:
        return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _p(value: object, style: ParagraphStyle = table_body) -> Paragraph:
        return Paragraph(_text(value), style)

    def _render_table(headers: list[str], rows: list[list[object]], column_widths: list[float]) -> Table:
        data = [[Paragraph(_text(header), table_header) for header in headers]]
        for row in rows:
            data.append([_p(value) for value in row])

        table = Table(data, colWidths=column_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe7f3")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c8d2dc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return table

    receipt_type = str(receipt.get("receipt_type") or "").strip().upper() or "UNKNOWN"
    organization_name = "Unknown"
    organization_snapshot = receipt.get("organization_snapshot")
    if isinstance(organization_snapshot, dict):
        organization_name = str(organization_snapshot.get("organization") or "").strip() or "Unknown"
    acknowledgment = receipt.get("acknowledgment")
    ack_timestamp = ""
    if isinstance(acknowledgment, dict):
        ack_timestamp = str(acknowledgment.get("ack_at") or "").strip()
    if not ack_timestamp:
        ack_timestamp = str(receipt.get("commit_at") or "").strip()

    typed_name = _receipt_pdf_ack_name(receipt)
    location_summary = _receipt_pdf_location_summary(receipt)
    receipt_type_label = _receipt_type_label(receipt_type)
    asset_count = sum(1 for asset in receipt.get("assets", []) if isinstance(asset, dict))
    asset_count_label = f"{asset_count} asset" if asset_count == 1 else f"{asset_count} assets"
    action_phrase = "issued to"
    if receipt_type == "RETURN":
        action_phrase = "returned from"
    elif receipt_type not in {"ISSUE", "RETURN"}:
        action_phrase = "recorded for"

    delivery = receipt.get("delivery")
    delivery_state = ""
    delivery_error = ""
    if isinstance(delivery, dict):
        delivery_state = str(delivery.get("state") or "").strip().lower()
        delivery_error = str(delivery.get("last_error") or "").strip()

    if for_email:
        status_text = "Receipt attached for your records."
    elif delivery_state == "failed":
        status_text = "Receipt email failed. Resend recommended."
    elif delivery_state == "pending":
        status_text = "Receipt email queued. No action needed unless delivery stalls."
    else:
        status_text = "No action needed."

    recorded_at = _receipt_display_timestamp(ack_timestamp or receipt.get("commit_at"))
    summary_rows = [
        ["Action", receipt_type_label],
        ["Assets in this receipt", str(asset_count)],
        ["Recorded at", recorded_at or "Unknown"],
        ["Holder", typed_name],
        ["Organization", organization_name],
        ["Location", location_summary],
    ]
    audit_rows = [
        ["Receipt ID", str(receipt.get("id") or "Unknown")],
        ["Receipt key", str(receipt.get("receipt_key") or "Unknown")],
        ["Acknowledgment", _receipt_acknowledgment_statement(receipt_type)],
        ["Typed name", typed_name],
        ["Initials", _receipt_pdf_initials(typed_name)],
    ]
    recipient_email = str(receipt.get("recipient_email") or "").strip().lower()
    if recipient_email:
        audit_rows.append(["Recipient email", recipient_email])
    if delivery_error:
        audit_rows.append(["Delivery issue", delivery_error])

    asset_rows: list[list[object]] = []

    for asset in receipt.get("assets", []):
        if not isinstance(asset, dict):
            continue
        make_model = str(asset.get("manufacturer") or "").strip()
        model = str(asset.get("model") or "").strip()
        model_code = str(asset.get("model_code") or "").strip()
        if model:
            make_model = f"{make_model} / {model}" if make_model else model
        if model_code:
            make_model = f"{make_model} ({model_code})" if make_model else model_code
        asset_rows.append(
            [
                str(asset.get("asset_tag") or "").strip(),
                str(asset.get("equipment_type") or "").strip(),
                str(asset.get("serial_number") or "").strip(),
                make_model,
                _receipt_pdf_location_type_label(asset.get("from_location_type")),
                _receipt_pdf_location_type_label(asset.get("to_location_type")),
            ]
        )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title=f"AssetTrack Receipt {receipt.get('receipt_key') or receipt.get('id')}",
        author="AssetTrack",
    )

    story: list[object] = [
        Paragraph(receipt_type_label, title),
        Spacer(1, 0.1 * inch),
        Paragraph(f"{_text(asset_count_label)} {action_phrase} {_text(typed_name)}", hero),
        Paragraph(_text(status_text), status),
        Paragraph(
            _text(" · ".join(part for part in [recorded_at or "Unknown", organization_name, location_summary] if part)),
            supporting,
        ),
        Spacer(1, 0.08 * inch),
        Paragraph("What Happened", heading),
        Spacer(1, 0.05 * inch),
        _render_table(
            ["Question", "Answer"],
            summary_rows,
            [1.8 * inch, 5.2 * inch],
        ),
        Spacer(1, 0.16 * inch),
        Spacer(1, 0.18 * inch),
        Paragraph("Assets", heading),
        Spacer(1, 0.08 * inch),
        _render_table(
            ["Tag", "Type", "Serial", "Item", "From", "To"],
            asset_rows or [["No assets captured.", "", "", "", "", ""]],
            [1.15 * inch, 1.0 * inch, 1.25 * inch, 1.95 * inch, 0.95 * inch, 1.0 * inch],
        ),
    ]

    if not for_email:
        story.extend(
            [
                Spacer(1, 0.16 * inch),
                Paragraph("Audit Details", heading),
                Spacer(1, 0.05 * inch),
                _render_table(
                    ["Detail", "Recorded value"],
                    audit_rows,
                    [1.8 * inch, 5.2 * inch],
                ),
            ]
        )

    def _invariant_canvas(*args, **kwargs):
        kwargs.setdefault("invariant", 1)
        return canvas.Canvas(*args, **kwargs)

    doc.build(story, canvasmaker=_invariant_canvas)
    pdf_bytes = buffer.getvalue()
    stable_digest = hashlib.md5(json.dumps(receipt, sort_keys=True).encode("utf-8")).hexdigest().encode("ascii")
    return re.sub(
        rb"/ID\s*\[\s*<[^>]+>\s*<[^>]+>\s*\]",
        b"/ID [<" + stable_digest + b"><" + stable_digest + b">]",
        pdf_bytes,
        count=1,
    )


def _update_receipt_delivery_state(
    conn,
    *,
    receipt_id: int,
    snapshot: dict[str, object],
    state: str,
    last_attempt_at: Optional[str],
    sent_at: Optional[str],
    last_error: Optional[str],
) -> None:
    updated_snapshot = dict(snapshot)
    updated_snapshot["delivery"] = _receipt_delivery_snapshot(
        state=state,
        sent_at=sent_at,
        last_attempt_at=last_attempt_at,
        last_error=last_error,
    )
    conn.execute(
        """
        UPDATE receipt_queue
        SET snapshot_json = ?, sent_at = ?, last_attempt_at = ?, last_error = ?
        WHERE id = ?;
        """,
        (
            json.dumps(updated_snapshot, sort_keys=True),
            sent_at,
            last_attempt_at,
            last_error,
            int(receipt_id),
        ),
    )


def _send_queued_receipt(receipt_id: int) -> dict[str, object]:
    conn = get_connection()
    try:
        row = _receipt_queue_row_by_id(conn, receipt_id)
        if row is None:
            raise ValueError("Receipt not found.")

        snapshot = _receipt_row_snapshot(row)
        delivery = _receipt_delivery_from_row(row, snapshot)
        delivery_state = str(delivery.get("state") or "").strip().lower()
        if delivery_state not in {"pending", "failed"}:
            raise ValueError("Receipt is not queued for email.")

        receipt = _receipt_from_queue_row(row)
        attempt_at = datetime.now(timezone.utc).isoformat()

        try:
            recipients = _send_receipt_email(receipt)
        except Exception as exc:
            with conn:
                _update_receipt_delivery_state(
                    conn,
                    receipt_id=int(row["id"]),
                    snapshot=snapshot,
                    state="failed",
                    last_attempt_at=attempt_at,
                    sent_at=None,
                    last_error=str(exc),
                )
            raise

        with conn:
            _update_receipt_delivery_state(
                conn,
                receipt_id=int(row["id"]),
                snapshot=snapshot,
                state="sent",
                last_attempt_at=attempt_at,
                sent_at=attempt_at,
                last_error=None,
            )

        return {
            "receipt_id": int(row["id"]),
            "recipients": recipients,
            "sent_at": attempt_at,
        }
    finally:
        conn.close()


@app.get("/receipts")
@require_login
def receipts_list():
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    asset_tag = (request.args.get("asset_tag") or "").strip()
    holder_name = (request.args.get("holder_name") or "").strip()
    building_room = (request.args.get("building_room") or "").strip()

    clauses: list[str] = []
    params: list[object] = []

    if asset_tag:
        clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM json_each(receipt_queue.snapshot_json, '$.assets') AS asset
                WHERE UPPER(COALESCE(json_extract(asset.value, '$.asset_tag'), '')) LIKE UPPER(?)
            )
            """
        )
        params.append(f"%{asset_tag}%")

    if holder_name:
        clauses.append(
            """
            (
                UPPER(COALESCE(json_extract(receipt_queue.snapshot_json, '$.holder_snapshot.name'), '')) LIKE UPPER(?)
                OR EXISTS (
                    SELECT 1
                    FROM json_each(receipt_queue.snapshot_json, '$.assets') AS asset
                    WHERE UPPER(COALESCE(json_extract(asset.value, '$.holder_snapshot.name'), '')) LIKE UPPER(?)
                       OR UPPER(COALESCE(json_extract(asset.value, '$.from_holder_snapshot.name'), '')) LIKE UPPER(?)
                )
            )
            """
        )
        like_value = f"%{holder_name}%"
        params.extend([like_value, like_value, like_value])

    if building_room:
        clauses.append(
            """
            (
                UPPER(COALESCE(json_extract(receipt_queue.snapshot_json, '$.location_context.building_room'), '')) LIKE UPPER(?)
                OR EXISTS (
                    SELECT 1
                    FROM json_each(receipt_queue.snapshot_json, '$.assets') AS asset
                    WHERE UPPER(COALESCE(json_extract(asset.value, '$.from_building_room'), '')) LIKE UPPER(?)
                       OR UPPER(COALESCE(json_extract(asset.value, '$.to_building_room'), '')) LIKE UPPER(?)
                )
            )
            """
        )
        like_value = f"%{building_room}%"
        params.extend([like_value, like_value, like_value])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT
                id,
                receipt_key,
                receipt_type,
                snapshot_json,
                commit_at,
                commit_operator_user_id,
                holder_id,
                sent_at,
                last_attempt_at,
                last_error
            FROM receipt_queue
            {where_sql}
            ORDER BY commit_at DESC, id DESC;
            """,
            tuple(params),
        ).fetchall()
    finally:
        conn.close()

    receipts = [
        _receipt_summary_from_row(
            row,
            asset_tag_filter=asset_tag,
            holder_name_filter=holder_name,
            building_room_filter=building_room,
        )
        for row in rows
    ]

    return render_template(
        "receipts_list.html",
        receipts=receipts,
        filters={
            "asset_tag": asset_tag,
            "holder_name": holder_name,
            "building_room": building_room,
        },
    )


@app.post("/receipts/<int:receipt_id>/send")
@require_login
def receipt_send(receipt_id: int):
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        if wants_json():
            return {"ok": False, "error": "Locked"}, 401
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    try:
        result = _send_queued_receipt(receipt_id)
    except ValueError as exc:
        if wants_json():
            return {"ok": False, "error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("receipt_detail", receipt_id=receipt_id))
    except Exception as exc:
        if wants_json():
            return {"ok": False, "error": str(exc)}, 500
        flash(f"Receipt email failed: {exc}", "error")
        return redirect(url_for("receipt_detail", receipt_id=receipt_id))

    if wants_json():
        return {
            "ok": True,
            "receipt_id": result["receipt_id"],
            "recipients": result["recipients"],
            "sent_at": result["sent_at"],
        }

    flash(f"Receipt email sent to {', '.join(result['recipients'])}.", "success")
    return redirect(url_for("receipt_detail", receipt_id=receipt_id))


@app.get("/receipts/<int:receipt_id>/pdf")
@require_login
def receipt_pdf(receipt_id: int):
    authed = enforce_inactivity_timeout()
    if auth_enabled() and not authed:
        flash("Locked. Re-enter access code.", "error")
        return redirect(url_for("intake"))

    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                id,
                receipt_key,
                receipt_type,
                source_event_ids_json,
                snapshot_json,
                commit_at,
                commit_operator_user_id,
                holder_id,
                sent_at,
                last_attempt_at,
                last_error
            FROM receipt_queue
            WHERE id = ?
            LIMIT 1;
            """,
            (receipt_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        abort(404)

    receipt = _receipt_from_queue_row(row)
    pdf_bytes = _build_receipt_pdf(receipt)
    download_name = _receipt_pdf_download_name(receipt)
    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=download_name,
        mimetype="application/pdf",
        conditional=False,
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
        form = {"name": "", "organization_id": "", "email": ""}

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
    email = (request.form.get("email") or "").strip()
    form = {"name": name, "organization_id": organization_id_raw, "email": email}

    if not email:
        session["holder_new_form"] = form
        flash(_holder_form_error_message(ValueError("email is required")), "error")
        if return_to is not None:
            return redirect(url_for("holders_new", return_to=return_to))
        return redirect(url_for("holders_new"))

    try:
        created = create_holder(
            name,
            organization_id=None if not organization_id_raw else int(organization_id_raw),
            email=email,
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
            "email": str(holder.get("email") or ""),
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
        "email": (request.form.get("email") or "").strip(),
    }

    holder = get_holder(holder_id)
    if holder is None:
        abort(404)

    if not form["email"]:
        session[f"holder_edit_form:{holder_id}"] = form
        flash(_holder_form_error_message(ValueError("email is required")), "error")
        if return_to is not None:
            return redirect(url_for("holders_edit", holder_id=holder_id, return_to=return_to))
        return redirect(url_for("holders_edit", holder_id=holder_id))

    try:
        updated = update_holder(
            holder_id,
            name=form["name"],
            organization_id=None if not form["organization_id"] else int(form["organization_id"]),
            email=form["email"],
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
    for user in users:
        user["created_at_display"] = _receipt_display_timestamp(user.get("created_at"))
        user["updated_at_display"] = _receipt_display_timestamp(user.get("updated_at"))
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


def _load_admin_human_report_data(resolved_db_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{resolved_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    try:
        asset_summary_row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_assets,
                SUM(CASE WHEN location_type = 'STORAGE' THEN 1 ELSE 0 END) AS storage_assets,
                SUM(CASE WHEN location_type = 'IN_CUSTODY' THEN 1 ELSE 0 END) AS in_custody_assets,
                SUM(CASE WHEN location_type = 'DISPOSED' THEN 1 ELSE 0 END) AS disposed_assets
            FROM assets;
            """
        ).fetchone()

        assets = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    a.asset_tag,
                    COALESCE(a.equipment_type, '') AS equipment_type,
                    COALESCE(a.manufacturer, '') AS manufacturer,
                    COALESCE(a.model, '') AS model,
                    COALESCE(a.location_type, '') AS location_type,
                    h.id AS holder_detail_id,
                    COALESCE(h.name, '') AS holder_name,
                    COALESCE(h.organization, '') AS holder_organization,
                    COALESCE(s.case_name, '') AS home_case_name,
                    s.slot_position AS home_slot_position,
                    COALESCE(s.case_name || ' / ' || s.slot_position, '') AS home_slot
                FROM assets a
                LEFT JOIN holders h
                  ON h.id = a.current_holder_id
                LEFT JOIN slots s
                  ON s.id = a.home_slot_id
                ORDER BY a.asset_tag COLLATE NOCASE ASC, a.id ASC;
                """
            ).fetchall()
        ]

        holders = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    h.id,
                    h.holder_type,
                    h.name,
                    COALESCE(h.organization, '') AS organization,
                    COALESCE(h.identifier, '') AS identifier,
                    COUNT(a.id) AS assets_in_custody
                FROM holders h
                LEFT JOIN assets a
                  ON a.current_holder_id = h.id
                 AND a.location_type = 'IN_CUSTODY'
                GROUP BY h.id, h.holder_type, h.name, h.organization, h.identifier
                ORDER BY h.name COLLATE NOCASE ASC, h.id ASC;
                """
            ).fetchall()
        ]

        organizations = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    o.id,
                    o.name,
                    COUNT(DISTINCT ob.building_id) AS building_count
                FROM organizations o
                LEFT JOIN organization_buildings ob
                  ON ob.organization_id = o.id
                GROUP BY o.id, o.name
                ORDER BY o.name COLLATE NOCASE ASC, o.id ASC;
                """
            ).fetchall()
        ]

        organization_building_mappings = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    o.name AS organization_name,
                    b.name AS building_name
                FROM organization_buildings ob
                JOIN organizations o
                  ON o.id = ob.organization_id
                JOIN buildings b
                  ON b.id = ob.building_id
                ORDER BY o.name COLLATE NOCASE ASC, b.name COLLATE NOCASE ASC;
                """
            ).fetchall()
        ]

        current_custody = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    h.id AS holder_detail_id,
                    h.name AS holder_name,
                    COALESCE(h.organization, '') AS organization,
                    a.asset_tag,
                    COALESCE(a.equipment_type, '') AS equipment_type,
                    COALESCE(a.building_room, '') AS current_location
                FROM assets a
                JOIN holders h
                  ON h.id = a.current_holder_id
                WHERE a.location_type = 'IN_CUSTODY'
                ORDER BY h.name COLLATE NOCASE ASC, a.asset_tag COLLATE NOCASE ASC, a.id ASC;
                """
            ).fetchall()
        ]

        recent_active_events = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT
                    e.id,
                    e.event_date,
                    e.asset_tag,
                    e.event_type,
                    h.id AS holder_detail_id,
                    COALESCE(h.name, '') AS holder_name,
                    COALESCE(h.organization, '') AS holder_organization
                FROM asset_events e
                LEFT JOIN holders h
                  ON h.id = e.holder_id
                WHERE {ACTIVE_EVENTS_WHERE.replace("id NOT IN", "e.id NOT IN", 1)}
                ORDER BY e.id DESC
                LIMIT 25;
                """
            ).fetchall()
        ]

        cases = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    s.case_name,
                    COUNT(*) AS total_slots,
                    COUNT(DISTINCT so.slot_id) AS occupied_slots
                FROM slots s
                LEFT JOIN slot_occupancy so
                  ON so.slot_id = s.id
                GROUP BY s.case_name
                ORDER BY s.case_name COLLATE NOCASE ASC;
                """
            ).fetchall()
        ]

        return {
            "asset_summary": {
                "total_assets": int(asset_summary_row["total_assets"] or 0),
                "storage_assets": int(asset_summary_row["storage_assets"] or 0),
                "in_custody_assets": int(asset_summary_row["in_custody_assets"] or 0),
                "disposed_assets": int(asset_summary_row["disposed_assets"] or 0),
            },
            "assets": assets,
            "holders": holders,
            "organizations": organizations,
            "organization_building_mappings": organization_building_mappings,
            "current_custody": current_custody,
            "recent_active_events": recent_active_events,
            "cases": cases,
        }
    finally:
        conn.close()


def _build_admin_human_report_pdf(report_data: dict, db_path: str) -> bytes:
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    heading = styles["Heading1"]
    section_heading = styles["Heading2"]
    title = styles["Title"]

    def _p(value: object) -> Paragraph:
        text = str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return Paragraph(text, body)

    def _render_table(headers: list[str], rows: list[list[object]], column_widths: list[float]) -> Table:
        data = [[Paragraph(f"<b>{header}</b>", body) for header in headers]]
        for row in rows:
            data.append([_p(value) for value in row])

        table = Table(data, colWidths=column_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe7f3")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c8d2dc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return table

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    story: list[object] = [
        Paragraph("Admin Human-Readable Report", title),
        Spacer(1, 0.15 * inch),
        Paragraph("Read-only report. The raw SQLite database backup remains authoritative.", body),
        Paragraph(f"Database path: {db_path}", body),
        Paragraph("Recent events section: recent active events only.", body),
        Spacer(1, 0.2 * inch),
        Paragraph("Assets", heading),
        Spacer(1, 0.08 * inch),
        Paragraph(
            (
                f"Total assets: {report_data['asset_summary']['total_assets']} | "
                f"In storage: {report_data['asset_summary']['storage_assets']} | "
                f"In custody: {report_data['asset_summary']['in_custody_assets']} | "
                f"Disposed: {report_data['asset_summary']['disposed_assets']}"
            ),
            body,
        ),
        Spacer(1, 0.1 * inch),
        _render_table(
            ["Asset Tag", "Type", "Make / Model", "Location Type", "Current Holder", "Home Slot"],
            [
                [
                    row["asset_tag"],
                    row["equipment_type"],
                    f"{row['manufacturer']}{' / ' + row['model'] if row['model'] else ''}",
                    row["location_type"],
                    (
                        f"{row['holder_name']} ({row['holder_organization']})"
                        if row["holder_name"] and row["holder_organization"] and row["holder_organization"] != row["holder_name"]
                        else row["holder_name"]
                    ),
                    row["home_slot"],
                ]
                for row in report_data["assets"]
            ]
            or [["No assets found.", "", "", "", "", ""]],
            [1.1 * inch, 0.8 * inch, 1.4 * inch, 1.1 * inch, 1.6 * inch, 1.0 * inch],
        ),
        Spacer(1, 0.2 * inch),
        Paragraph("Holders", section_heading),
        Spacer(1, 0.08 * inch),
        _render_table(
            ["ID", "Type", "Name", "Organization", "Identifier", "Assets In Custody"],
            [
                [
                    row["id"],
                    row["holder_type"],
                    row["name"],
                    row["organization"],
                    row["identifier"],
                    row["assets_in_custody"],
                ]
                for row in report_data["holders"]
            ]
            or [["No holders found.", "", "", "", "", ""]],
            [0.5 * inch, 0.9 * inch, 1.6 * inch, 1.5 * inch, 1.0 * inch, 0.9 * inch],
        ),
        Spacer(1, 0.2 * inch),
        Paragraph("Organizations and Building Access", section_heading),
        Spacer(1, 0.08 * inch),
        _render_table(
            ["Organization", "Mapped Buildings"],
            [[row["name"], row["building_count"]] for row in report_data["organizations"]]
            or [["No organizations found.", ""]],
            [4.5 * inch, 2.0 * inch],
        ),
        Spacer(1, 0.08 * inch),
        _render_table(
            ["Organization", "Building"],
            [
                [row["organization_name"], row["building_name"]]
                for row in report_data["organization_building_mappings"]
            ]
            or [["No organization-to-building mappings found.", ""]],
            [3.5 * inch, 3.0 * inch],
        ),
        Spacer(1, 0.2 * inch),
        Paragraph("Current Custody", section_heading),
        Spacer(1, 0.08 * inch),
        _render_table(
            ["Holder", "Organization", "Asset Tag", "Type", "Current Location"],
            [
                [
                    row["holder_name"],
                    row["organization"],
                    row["asset_tag"],
                    row["equipment_type"],
                    row["current_location"],
                ]
                for row in report_data["current_custody"]
            ]
            or [["No assets are currently in custody.", "", "", "", ""]],
            [1.5 * inch, 1.5 * inch, 1.1 * inch, 0.8 * inch, 2.0 * inch],
        ),
        Spacer(1, 0.2 * inch),
        Paragraph("Recent Active Events", section_heading),
        Spacer(1, 0.08 * inch),
        _render_table(
            ["ID", "When", "Asset Tag", "Event Type", "Holder"],
            [
                [
                    row["id"],
                    row["event_date"],
                    row["asset_tag"],
                    row["event_type"],
                    (
                        f"{row['holder_name']} ({row['holder_organization']})"
                        if row["holder_name"] and row["holder_organization"] and row["holder_organization"] != row["holder_name"]
                        else row["holder_name"]
                    ),
                ]
                for row in report_data["recent_active_events"]
            ]
            or [["No active events found.", "", "", "", ""]],
            [0.5 * inch, 1.8 * inch, 1.1 * inch, 1.0 * inch, 2.6 * inch],
        ),
        Spacer(1, 0.2 * inch),
        Paragraph("Location and Case Data", section_heading),
        Spacer(1, 0.08 * inch),
        _render_table(
            ["Case", "Total Slots", "Occupied Slots"],
            [
                [row["case_name"], row["total_slots"], row["occupied_slots"]]
                for row in report_data["cases"]
            ]
            or [["No case or slot data found.", "", ""]],
            [3.5 * inch, 1.5 * inch, 1.5 * inch],
        ),
    ]

    doc.build(story)
    return buffer.getvalue()


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


@app.get("/report")
@require_login
def human_report():
    resolved_db_path = _resolved_runtime_db_path()
    report_error: str | None = None
    report_data = {
        "asset_summary": {
            "total_assets": 0,
            "storage_assets": 0,
            "in_custody_assets": 0,
            "disposed_assets": 0,
        },
        "assets": [],
        "holders": [],
        "organizations": [],
        "organization_building_mappings": [],
        "current_custody": [],
        "recent_active_events": [],
        "cases": [],
    }

    try:
        report_data = _load_admin_human_report_data(resolved_db_path)
    except sqlite3.Error as exc:
        report_error = f"Could not read report data: {exc}"

    return render_template(
        "report_readonly.html",
        report_error=report_error,
        **report_data,
    )


@app.get("/admin/report")
@require_login
@require_role("admin")
def admin_human_report():
    resolved_db_path = _resolved_runtime_db_path()
    report_error: str | None = None
    report_data = {
        "asset_summary": {
            "total_assets": 0,
            "storage_assets": 0,
            "in_custody_assets": 0,
            "disposed_assets": 0,
        },
        "assets": [],
        "holders": [],
        "organizations": [],
        "organization_building_mappings": [],
        "current_custody": [],
        "recent_active_events": [],
        "cases": [],
    }

    try:
        report_data = _load_admin_human_report_data(resolved_db_path)
    except sqlite3.Error as exc:
        report_error = f"Could not read admin report data: {exc}"

    return render_template(
        "admin_human_report.html",
        db_path=str(resolved_db_path),
        report_error=report_error,
        **report_data,
    )


@app.get("/admin/report/pdf")
@require_login
@require_role("admin")
def admin_human_report_pdf():
    resolved_db_path = _resolved_runtime_db_path()
    try:
        report_data = _load_admin_human_report_data(resolved_db_path)
        pdf_bytes = _build_admin_human_report_pdf(report_data, str(resolved_db_path))
    except sqlite3.Error as exc:
        return f"Could not build admin PDF report: {exc}", 500

    download_name = f"assettrack-human-report-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.pdf"
    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=download_name,
        mimetype="application/pdf",
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
