# ⚠️ Disclaimer (Not Government Endorsed)

This software is an independent tool and is **not affiliated with, endorsed by, or sponsored by** the U.S. Department of War (DoW), U.S. Department of Defense (DoD), or any other government agency. Use of this software does **not** imply compliance with or substitution for official DoW/DoD policies, forms, or procedures. **You are responsible** for verifying accuracy and complying with all applicable regulations and for using official systems where required.

---

# AssetTrack

AssetTrack is an offline-first asset intake and accountability system designed for environments where reliability matters more than polish.

It provides a disciplined workflow for scanning physical assets, reviewing staged intake data, and committing records atomically to a local SQLite database. The system is intentionally simple, portable, and auditable.

AssetTrack supports:
- Barcode scanning into a preview queue
- Operator review with explicit confirmation before commit
- Atomic writes to SQLite (no partial state)
- Offline operation with no external service dependencies
- Dockerized deployment with explicit data persistence

AssetTrack is optimized for field use, controlled networks, and operational settings where accidental data loss, silent failures, or hidden state are unacceptable.

---

## Current Capabilities (Authoritative)

The sections below are in the process of being revised.  
The list here reflects the **current, verified behavior** of AssetTrack.

AssetTrack currently provides:
- Offline-first operation with no external service dependencies
- Barcode scanning into a staged **preview queue**
- Preview validation prior to commit
- Explicit operator review confirmation before commit
- Atomic commits to a local SQLite database
- Deterministic clearing of the preview queue on successful commit
- Dockerized execution with explicit host-mounted data persistence

Capabilities related to PDF generation, DA Form 2062, GUI tabs, recycle bins, or calibration tools are **not part of the current AssetTrack system** and will be removed or archived as documentation cleanup continues.

---

## 📌 Features

- **Scan --> Preview Queue**
  - Barcode scans stage rows into a preview queue (no immediate database writes).
  - Preview data can be validated before committing.

- **Review-Confirmed Commit**
  - Commits are intentionally gated by an explicit operator confirmation flag.
  - On success, commits write **atomically** to SQLite and the preview queue is cleared.

- **Offline-First Storage**
  - Data is stored locally in SQLite (no external services required).

- **Docker Support with Real Persistence**
  - Docker runs are supported, but SQLite persistence requires mounting host `./data` to container `/app/data`.
  - Without the bind mount, the database is container-local and disposable.

---

## Requirements

AssetTrack is intentionally minimal. The requirements below reflect the **current, supported runtime**.

### Runtime

- **Python:** 3.12
- **Operating System:** macOS, Linux, or Windows (tested primarily on macOS and Linux)
- **Database:** SQLite (local file-based storage)
- **Shell:** POSIX-compatible shell recommended for setup commands

### Python Dependencies

All Python dependencies are defined in `requirements.txt`.

No PDF generation libraries, GUI frameworks, or reporting toolkits are required or supported.

### Docker (Optional)

Docker is supported for packaging and deployment.

**Important:**  
SQLite persistence **requires** a host bind mount.

- Host directory: `./data`
- Container path: `/app/data`

Running without this bind mount will result in a container-local, disposable database.

### Hardware (Optional)

- USB barcode scanner operating in keyboard (HID) mode
- Tested with common handheld scanners; no vendor-specific SDKs required

---

## Quick Start

### Local (venv)

```bash
# from repo root
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt

# run the intake UI
python -m assettrack.intake.app
```

Then open <http://127.0.0.1:8000/>

### Docker (with persistence)

SQLite persistence requires a bind mount. **Without it**, the database will be **disposable**.

```bash
# build
docker build -t assettrack:local .

# run (persist ./data on the host)
docker run --rm -p 8000:8000 -v "$(pwd)/data:/app/data" assettrack:local
```

Then open <http://127.0.0.1:8000/>

---

## Acknowledgements

AssetTrack was built through iterative design, operational testing, and disciplined reduction of accidental complexity.

Thanks to:
- Open-source tooling that prioritizes clarity and composability
- Field operators whose workflows demand reliability over polish
- Prior iterations of this project, which informed what to remove as much as what to keep
- **:contentReference[oaicite:0]{index=0} (@CyberJrod)** for the initial iteration, early technical feedback, candid review, and pressure-testing assumptions