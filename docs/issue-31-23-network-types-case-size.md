# Issue 31-23 Network Types and Case Size Migration Plan

Why it matters: AssetTrack needs the full approved network inventory vocabulary and descriptive case metadata before the BQ26 workbook import, without rewriting custody or audit history.

## Non-Destructive Migration

- Add a new `case_metadata` table keyed by `case_name`.
- Store only descriptive `case_size` values from the approved menu, with blank allowed.
- Do not alter `slots`, `slot_occupancy`, `assets`, or `asset_events` rows during migration.
- Existing cases continue to derive from `slots`; cases without metadata display a blank or "Not recorded" Case Size.
- Slot count remains derived from actual `slots` rows only. Case Size never determines capacity.
- Startup bootstrap creates the table for new databases and existing databases through the established idempotent schema initializer.

## Approved Case Size Values

- Small Wheel
- Medium Wheel
- Large Wheel
- 16 Rack Unit Wheel
- 4 Rack Unit Wheel
- 6 Rack Unit Wheel
- 8 Rack Unit Wheel
- White Case
- SM-Case
