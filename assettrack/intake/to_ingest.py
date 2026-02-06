# assettrack/intake/to_ingest.py
"""
Translate intake Scan objects into the row shape the ingest pipeline expects.

Feynman-brief:
- Intake captures "what was scanned"
- Ingest expects a dict shaped like a CSV row
- This adapter keeps those worlds decoupled
"""
from __future__ import annotations
from datetime import timezone
from assettrack.intake.scan import Scan


def scan_to_ingest_row(scan: Scan) -> dict:
    """
    Convert an intake Scan into the ingest-row shape.

    This is preview-only. We do not commit anything here.
    We only fill what intake actually knows today and leave the rest blank.
    """
    scanned_at = scan.scanned_at
    if scanned_at.tzinfo is None:
        scanned_at = scanned_at.replace(tzinfo=timezone.utc)

    return {
        "asset_tag": scan.asset_tag,
        "timestamp": scanned_at.isoformat(),
        "event_type": "",         # intake does not know yet
        "issued_to_name": "",     # intake does not know yet
        "operator_id": scan.operator_id or "",
        "case_number": "",        # intake does not know yet
        "slot_number": "",        # intake does not know yet
        "building_room": "",      # optional, safe default
        "notes": "",              # optional, safe default
        "row_number": None,       # ingest validator may accept None
    }