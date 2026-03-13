# assettrack/intake/to_ingest.py
"""
Translate intake Scan objects into the row shape the ingest pipeline expects.

Feynman-brief:
- Scanner acts like a keyboard wedge.
- A wedge scan is a SCAN event.
- This adapter fills safe defaults so preview/validate/commit can work.
"""

from __future__ import annotations

import os
from datetime import timezone

from assettrack.intake.scan import Scan


DEFAULT_OPERATOR_ID = os.getenv("ASSETTRACK_OPERATOR_ID", "intake")


def scan_to_ingest_row(scan: Scan) -> dict:
    scanned_at = scan.scanned_at
    if scanned_at.tzinfo is None:
        scanned_at = scanned_at.replace(tzinfo=timezone.utc)

    operator_id = (scan.operator_id or DEFAULT_OPERATOR_ID or "").strip()
    equipment_type = (getattr(scan, "equipment_type", "") or "").strip() or "laptop"
    case_name = (getattr(scan, "case_name", "") or "").strip().upper()
    slot_position = getattr(scan, "slot_position", None)
    home_slot_id = getattr(scan, "home_slot_id", None)

    return {
        "asset_tag": (scan.asset_tag or "").strip().upper(),
        "timestamp": scanned_at.isoformat(),
        "event_type": "SCAN",
        "issued_to_name": "",   # not required for SCAN
        "operator_id": operator_id,
        "case_number": case_name,
        "slot_number": "" if slot_position is None else str(slot_position),
        "home_slot_id": home_slot_id,
        "building_room": "",    # optional
        "notes": "",            # optional
        "row_number": None,     # preview convenience
        "equipment_type": equipment_type,
    }
