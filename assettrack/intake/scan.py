# file: assettrack/intake/scan.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Scan:
    """
    A single intake scan event.

    Why this exists:
    - intake collects scan events (queue of Scan objects)
    - to_ingest.py adapts Scan -> ingest-shaped dict
    - equipment_type is stored per scan so later edits don't rewrite history
    """

    asset_tag: str
    scanned_at: datetime
    equipment_type: str = "laptop"
    operator_id: str | None = None
    home_slot_id: int | None = None
    case_name: str = ""
    slot_position: int | None = None

    @staticmethod
    def now(
        asset_tag: str,
        operator_id: str | None = None,
        equipment_type: str = "laptop",
        home_slot_id: int | None = None,
        case_name: str = "",
        slot_position: int | None = None,
    ) -> "Scan":
        """Convenience constructor for 'scan happened right now'."""
        equipment_type = (equipment_type or "").strip() or "laptop"
        return Scan(
            asset_tag=asset_tag,
            scanned_at=datetime.now(timezone.utc),
            operator_id=operator_id,
            equipment_type=equipment_type,
            home_slot_id=home_slot_id,
            case_name=(case_name or "").strip().upper(),
            slot_position=slot_position,
        )
