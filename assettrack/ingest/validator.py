# assettrack/ingest/validator.py
"""
Batch validation for offline ingest.

Consumes parsed rows from ingest.parser and produces
a validation preview with per-row errors.
"""

from typing import List, Dict, Any


REQUIRED_FIELDS = [
    "asset_tag",
    "timestamp",
    "event_type",
    "issued_to_name",
    "operator_id",
    "case_number",
    "slot_number",
]


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
