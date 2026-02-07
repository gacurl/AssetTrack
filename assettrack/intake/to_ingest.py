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

    return {
        "asset_tag": (scan.asset_tag or "").strip().upper(),
        "timestamp": scanned_at.isoformat(),
        "event_type": "SCAN",
        "issued_to_name": "",   # not required for SCAN
        "operator_id": operator_id,
        "case_number": "",      # optional for SCAN (validator controls)
        "slot_number": "",      # optional for SCAN (validator controls)
        "building_room": "",    # optional
        "notes": "",            # optional
        "row_number": None,     # preview convenience
        "equipment_type": "",   # may be required later for create; leaving blank for now
    }