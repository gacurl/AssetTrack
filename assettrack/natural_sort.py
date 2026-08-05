from __future__ import annotations

import re

_NATURAL_PART_RE = re.compile(r"(\d+)")


def natural_identifier_sort_key(value: object) -> tuple:
    label = str(value or "").strip()
    parts: list[tuple[int, object]] = []
    has_numeric_part = False
    for part in _NATURAL_PART_RE.split(label):
        if not part:
            continue
        if part.isdigit():
            has_numeric_part = True
            parts.append((0, int(part)))
        else:
            parts.append((1, part.upper()))
    numeric_group = 0 if has_numeric_part else 1
    return (numeric_group, tuple(parts), label)
