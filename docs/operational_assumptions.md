<!-- docs/operational_assumptions.md -->

# Operational assumptions

This document captures the assumptions AssetTrack makes about how it is used.
If any of these assumptions change, behavior may change — not because the software is wrong, but because the environment is different.

The goal is clarity, not blame.

---

## Operator assumptions

AssetTrack assumes:

- A human operator is present.
- Scans are intentional and paced by a person.
- Operators notice and correct mistakes when they happen.
- AssetTrack is not running unattended or fully automated.

If you need unattended automation, this tool is the wrong fit.

---

## Scanner assumptions

AssetTrack assumes:

- The scanner behaves like a keyboard.
- One trigger pull equals one barcode.
- Each scan ends with Enter.
- Scanner configuration is stable during a session.

AssetTrack does not compensate for misconfigured scanners.

---

## Data assumptions

AssetTrack assumes:

- Asset tags are unique.
- A scanned value represents a real, physical item.
- Operators are scanning the correct label type.
- Historical data should not be silently altered.

Once written, history stays written.

---

## Environment assumptions

AssetTrack assumes:

- Local disk is writable.
- SQLite is acceptable for the expected scale.
- The database file is backed up externally.
- Only one active writer is operating at a time.

If concurrency increases, the storage model must change.

---

## Security assumptions

AssetTrack assumes:

- The operator’s machine is trusted.
- Physical access implies authorization.
- Container scanning provides visibility, not guarantees.
- Security posture is reviewed periodically, not continuously.

Zero-risk is not the goal. Informed risk is.

---

## Change guidance

If an assumption here no longer holds:

- Stop.
- Update this document.
- Then change the code or process.

Documentation changes come first for a reason.