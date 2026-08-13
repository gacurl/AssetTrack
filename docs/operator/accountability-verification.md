# Accountability Verification

Run this check before handoff, audit review, or any operational moment where every active asset must be confirmed checked in.

Command:

```bash
.venv/bin/python scripts/verify_accountability.py --db data/assettrack.db
```

`PASS` means every active, non-retired asset is confirmed checked in: current state is `STORAGE`, no current holder is attached, and custody events do not contradict that state.

`FAIL` means at least one active asset is issued or cannot be proven checked in from current state and active custody events. Read each exception line for the asset tag, serial number, asset type, current holder when present, storage location when present, and latest custody event.

The script is read-only. It does not create Return events, repair records, or change custody state.
