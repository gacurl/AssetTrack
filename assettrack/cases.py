from __future__ import annotations

import sqlite3

CASE_SIZE_OPTIONS = (
    "Small Wheel",
    "Medium Wheel",
    "Large Wheel",
    "16 Rack Unit Wheel",
    "4 Rack Unit Wheel",
    "6 Rack Unit Wheel",
    "8 Rack Unit Wheel",
    "White Case",
    "SM-Case",
)


def normalize_case_size(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for option in CASE_SIZE_OPTIONS:
        if text == option:
            return option
    raise ValueError("case_size must be one of the approved Case Size choices.")


def save_case_size(conn: sqlite3.Connection, case_name: object, case_size: object) -> str:
    normalized_case = str(case_name or "").strip().upper()
    if not normalized_case:
        raise ValueError("case_name is required.")

    normalized_size = normalize_case_size(case_size)
    conn.execute(
        """
        INSERT INTO case_metadata (case_name, case_size)
        VALUES (?, ?)
        ON CONFLICT(case_name) DO UPDATE SET case_size = excluded.case_size;
        """,
        (normalized_case, normalized_size),
    )
    return normalized_size
