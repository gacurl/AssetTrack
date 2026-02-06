# file: assettrack/intake/scan.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Scan:
    """
    A single intake scan event.

    Why this exists:
    - intake collects "raw-ish" scan events (queue of Scan objects)
    - to_ingest.py adapts Scan -> ingest-shaped dict (preview-only for now)
    """

    asset_tag: str
    scanned_at: datetime
    operator_id: str | None = None

    @staticmethod
    def now(asset_tag: str, operator_id: str | None = None) -> "Scan":
        """Convenience constructor for "scan happened right now"."""
        return Scan(asset_tag=asset_tag, scanned_at=datetime.now(timezone.utc), operator_id=operator_id)
