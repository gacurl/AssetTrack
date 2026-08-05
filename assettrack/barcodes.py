from __future__ import annotations


def barcode_lookup_key(value: object) -> str:
    text = str(value or "").strip().upper()
    return "".join(character for character in text if character not in {" ", "-"})
