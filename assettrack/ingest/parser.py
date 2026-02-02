# assettrack/ingest/parser.py
"""
Batch CSV parser for AssetTrack offline ingest.

Responsibilities (and only these):
- Read a CSV file
- Normalize headers
- Preserve row order
- Attach row numbers
- Return structured rows

No validation. No database access.
"""

import csv
from pathlib import Path
from typing import List, Dict


def _normalize_header(name: str) -> str:
    """
    Normalize CSV headers so we don't depend on exact casing.
    """
    return name.strip().lower()


def parse_batch(csv_path: str | Path) -> List[Dict]:
    """
    Parse a batch CSV file into structured rows.

    Returns a list of dicts with:
      - row_number (1-based, data rows only)
      - data (dict of column -> value)
    """
    csv_path = Path(csv_path)

    rows: List[Dict] = []

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)

        try:
            raw_headers = next(reader)
        except StopIteration:
            return rows  # empty file

        headers = [_normalize_header(h) for h in raw_headers]

        for index, values in enumerate(reader, start=1):
            data = dict(zip(headers, values))

            rows.append(
                {
                    "row_number": index,
                    "data": data,
                }
            )

    return rows
