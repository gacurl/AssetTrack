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

    @staticmethod
    def now(
        asset_tag: str,
        operator_id: str | None = None,
        equipment_type: str = "laptop",
    ) -> "Scan":
        """Convenience constructor for 'scan happened right now'."""
        equipment_type = (equipment_type or "").strip() or "laptop"
        return Scan(
            asset_tag=asset_tag,
            scanned_at=datetime.now(timezone.utc),
            operator_id=operator_id,
            equipment_type=equipment_type,
        )