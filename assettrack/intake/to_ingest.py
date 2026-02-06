# assettrack/intake/to_ingest.py
"""
Translate intake Scan objects into the row shape the ingest pipeline expects.

Feynman-brief:
- Intake captures "what was scanned"
- Ingest expects a dict shaped like a CSV row
- This adapter keeps those worlds decoupled
"""

from __future__ import annotations

from datetime import datetime

from assettrack.intake.scan import Scan


def scan_to_ingest_row(scan: Scan) -> dict[str, object]:
    """
    Produce an ingest-compatible row dict.

    Notes:
    - We keep fields explicit, even if some are None for now.
    - Timestamp is ISO-8601 so it matches CSV-like expectations.
    """
    return {
        "asset_tag": scan.asset_tag,
        "timestamp": scan.scanned_at.replace(tzinfo=None).isoformat(timespec="seconds"),
        "operator_id": scan.operator_id,
        # Fields we don't have yet (future UI inputs / workflow):
        "event_type": None,
        "issued_to_name": None,
        "building_room": None,
        "case_number": None,
        "slot_number": None,
        "notes": None,
    }