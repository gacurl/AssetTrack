# file: assettrack/event_types.py
from __future__ import annotations

ISSUE_EVENT_TYPE = "ISSUE"
RETURN_EVENT_TYPE = "RETURN"

_LEGACY_TO_CANONICAL = {
    "STOCK_OUT": ISSUE_EVENT_TYPE,
    "STOCK_IN": RETURN_EVENT_TYPE,
}


def normalize_event_type(db_value: object) -> str:
    raw = str(db_value or "").strip().upper()
    if not raw:
        return ""
    if raw in {ISSUE_EVENT_TYPE, RETURN_EVENT_TYPE}:
        return raw
    return _LEGACY_TO_CANONICAL.get(raw, raw)


def issue_event_type_values() -> tuple[str, ...]:
    return ISSUE_EVENT_TYPE, "STOCK_OUT"


def return_event_type_values() -> tuple[str, ...]:
    return RETURN_EVENT_TYPE, "STOCK_IN"
