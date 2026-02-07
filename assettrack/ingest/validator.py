# assettrack/ingest/validator.py
"""
Batch validation for offline ingest.

Consumes parsed rows from ingest.parser and produces
a validation preview with per-row errors.

Feynman-brief:
- Not every event needs the same fields.
- SCAN is lightweight; ISSUE is strict.
- Validation is what protects commit-as-a-unit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
import re


ALLOWED_EVENT_TYPES = {
    "SCAN",
    "ISSUE",
    "RETURN",
    "UPDATE",
    "RETIRE",
}

ASSET_TAG_RE = re.compile(r"^[A-Z0-9-]+$")


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _normalize_event_type(value: Any) -> str:
    return str(value or "").strip().upper()


def _is_iso8601_timestamp(value: str) -> bool:
    """
    Accepts ISO-8601 timestamps, including 'Z' for UTC.
    """
    s = (value or "").strip()
    if not s:
        return False

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False


def _required_fields_for(event_type: str) -> List[str]:
    """
    Define required fields per event type.
    Keep this simple and explicit for MVP.
    """
    base = ["asset_tag", "timestamp", "event_type", "operator_id"]

    if event_type == "SCAN":
        return base

    if event_type == "ISSUE":
        return base + ["issued_to_name", "case_number", "slot_number"]

    # For now, require location for other state-changing events too.
    if event_type in {"RETURN", "UPDATE", "RETIRE"}:
        return base + ["case_number", "slot_number"]

    # Unknown event types will be flagged earlier; return base as fallback.
    return base


def validate_rows(parsed_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    overall_valid = True

    for row in parsed_rows:
        errors: List[str] = []
        data = row.get("data", {}) or {}
        row_number = row.get("row_number")

        asset_tag = str(data.get("asset_tag", "")).strip().upper()
        event_type = _normalize_event_type(data.get("event_type"))
        timestamp = str(data.get("timestamp", "")).strip()

        # event_type must be present + allowed before we can pick required fields
        if _is_blank(event_type):
            errors.append("Missing required field: event_type")
            required_fields = ["asset_tag", "timestamp", "operator_id"]
        else:
            if event_type not in ALLOWED_EVENT_TYPES:
                errors.append(
                    f"Invalid event_type: {data.get('event_type')} (allowed: {sorted(ALLOWED_EVENT_TYPES)})"
                )
            required_fields = _required_fields_for(event_type)

        # Required field checks
        for field in required_fields:
            value = data.get(field)
            if _is_blank(value):
                errors.append(f"Missing required field: {field}")

        # asset_tag format check
        if asset_tag and not ASSET_TAG_RE.match(asset_tag):
            errors.append(
                f"Invalid asset_tag (allowed A-Z, 0-9, '-'): {data.get('asset_tag')}"
            )

        # timestamp check
        if timestamp and not _is_iso8601_timestamp(timestamp):
            errors.append(f"Invalid timestamp (expected ISO-8601): {timestamp}")

        # OUT pairing rule (still applies when either field is present)
        case_number = str(data.get("case_number", "")).strip().upper()
        slot_number = str(data.get("slot_number", "")).strip().upper()
        if (case_number == "OUT") != (slot_number == "OUT"):
            errors.append("case_number and slot_number must both be OUT (or neither)")

        if errors:
            overall_valid = False

        rows.append({"row_number": row_number, "errors": errors, "data": data})

    return {"valid": overall_valid, "rows": rows}