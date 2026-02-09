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

## ⚠️ Legacy Documentation Notice ⚠️

The sections below this point reflect **historical or transitional documentation** from earlier iterations of the project and are being reviewed.

They may reference capabilities, workflows, or artifacts that are **not part of the current AssetTrack system**. These sections will be either updated, moved to a legacy archive, or removed as documentation cleanup continues.

For the authoritative description of current behavior, refer to:
- **About**
- **Current Capabilities**
- **Features**

---