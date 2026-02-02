# assettrack/ingest/validator.py
"""
Batch validation for offline ingest.

Consumes parsed rows from ingest.parser and produces
a validation preview with per-row errors.
"""

from typing import List, Dict, Any
from datetime import datetime
import re

REQUIRED_FIELDS = [
    "asset_tag",
    "timestamp",
    "event_type",
    "issued_to_name",
    "operator_id",
    "case_number",
    "slot_number",
]

ALLOWED_EVENT_TYPES = {
    "SCAN",
    "ISSUE",
    "RETURN",
    "UPDATE",
    "RETIRE",
}

CREATE_HINT_FIELDS = {
    "serial_number",
    "manufacturer",
    "model",
    "model_code",
    "building_room",
    "notes",
}

ASSET_TAG_RE = re.compile(r"^[A-Z0-9-]+$")

def _is_iso8601_timestamp(value: str) -> bool:
    """
    Accepts ISO-8601 timestamps, including 'Z' for UTC.
    """
    s = (value or "").strip()
    if not s:
        return False

    # Python's fromisoformat doesn't accept 'Z' directly.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False

def validate_rows(parsed_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    overall_valid = True

    for row in parsed_rows:
        errors = []
        data = row.get("data", {})
        row_number = row.get("row_number")

        for field in REQUIRED_FIELDS:
            value = data.get(field)
            if value is None or str(value).strip() == "":
                errors.append(f"Missing required field: {field}")
        
        asset_tag = str(data.get("asset_tag", "")).strip().upper()
        if asset_tag and not ASSET_TAG_RE.match(asset_tag):
            errors.append(f"Invalid asset_tag (allowed A-Z, 0-9, '-'): {data.get('asset_tag')}")

        event_type = data.get("event_type")
        if event_type:
            event_type_normalized = str(event_type).strip().upper()
            if event_type_normalized not in ALLOWED_EVENT_TYPES:
                errors.append(
                    f"Invalid event_type: {event_type} (allowed: {sorted(ALLOWED_EVENT_TYPES)})"
                )
        
        timestamp = data.get("timestamp")
        if timestamp and not _is_iso8601_timestamp(str(timestamp)):
            errors.append(f"Invalid timestamp (expected ISO-8601): {timestamp}")

        # TODO (Issue 3-4): enforce create rule:
        # If asset_tag does not exist, require equipment_type.
        # Needs DB existence check, not heuristics.

        if errors:
            overall_valid = False

        rows.append(
            {
                "row_number": row_number,
                "errors": errors,
                "data": data,
            }
        )

    return {
        "valid": overall_valid,
        "rows": rows,
    }
