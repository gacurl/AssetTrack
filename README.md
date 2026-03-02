
# ⚠️ Disclaimer (Not Government Endorsed)

This software is an independent tool and is **not affiliated with, endorsed by, or sponsored by** the U.S. Department of War (DoW), U.S. Department of Defense (DoD), or any other government agency. Use of this software does **not** imply compliance with or substitution for official DoW/DoD policies, forms, or procedures. **You are responsible** for verifying accuracy and complying with all applicable regulations and for using official systems where required.

---

# 🚜 AssetTrack

AssetTrack is an **offline-first asset intake and accountability system** built for operational environments where reliability, determinism, and auditability matter more than visual polish.

It provides a disciplined workflow for:

* Scanning physical assets
* Reviewing staged intake data
* Committing records atomically
* Preserving a durable, auditable event log

The system is intentionally minimal, portable, and designed to fail closed.

---

## System Model (Authoritative)

AssetTrack operates under three core principles:

1. **No silent writes** — changes are previewed before commit.
2. **Atomic state transitions** — no partial database updates.
3. **Explicit persistence** — data durability is intentional, not accidental.

Current architecture includes:

* Offline-first Flask UI
* SQLite storage
* Deterministic event logging
* Dockerized runtime
* Named-volume persistence
* Clean container security baseline (Trivy: 0 vulnerabilities)

Root (`/`) routes to login.
Authenticated users land on the operational dashboard.

---

## Current Capabilities

AssetTrack currently provides:

* Barcode scanning into a staged preview queue
* Operator validation before commit
* Explicit confirmation gating
* Atomic SQLite commits
* Deterministic clearing of the preview queue on success
* Persistent event logging
* Docker-based deployment with named volume durability

Not included:

* PDF generation
* DA Form 2062 automation
* GUI tab systems
* Reporting dashboards beyond current scope
* External service integrations

---

## Requirements

### Runtime

* Python 3.12
* macOS, Linux, or Windows
* SQLite (local file-based database)

### Optional Hardware

* USB barcode scanner (HID keyboard mode)

---

# 🚀 Quick Start

AssetTrack supports:

* Local virtual environment execution
* Docker (recommended for operational parity)
* Windows via WSL2 + Docker Desktop

---

## Option 1 — Local (venv)

From the repository root:

```
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m assettrack.intake.app
```

Then open:

[http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## Option 2 — Docker (Recommended)

Docker Compose is the authoritative deployment path.

Run:

```
docker compose up -d --build
```

Then open:

[http://localhost:8000](http://localhost:8000)

---

## Persistence Model (Important)

AssetTrack uses a named Docker volume mounted to:

```
/app/data
```

This means:

* Database survives container restarts
* Database survives `docker compose down`
* Data resets only if the Docker volume is explicitly removed

To inspect volumes:

```
docker volume ls
```

To remove the AssetTrack volume (destructive):

```
docker volume rm assettrack_data
```

The database path inside the container is controlled by:

```
ASSETTRACK_DB_PATH
```

Default resolves to:

```
/app/data/assettrack.db
```

---

## Verifying Docker persistence (data survives restarts)

Use this manual check to prove holder data survives container restarts.

1. Start the app:

```
docker compose up -d --build
```

2. In the UI (`http://localhost:8000`), create a holder from:
   `Holders` -> `Add Holder` (example name: `ZZ Persist Check`).

3. Confirm it is searchable before restart:

```
docker compose exec -T assettrack python - <<'PY'
import sqlite3
conn = sqlite3.connect("/app/data/assettrack.db")
rows = conn.execute(
    "SELECT id, name FROM holders WHERE name = ?;",
    ("ZZ Persist Check",),
).fetchall()
print(rows)
conn.close()
PY
```

4. Restart containers:

```
docker compose down
docker compose up -d
```

5. Confirm holder still exists after restart (same query):

```
docker compose exec -T assettrack python - <<'PY'
import sqlite3
conn = sqlite3.connect("/app/data/assettrack.db")
rows = conn.execute(
    "SELECT id, name FROM holders WHERE name = ?;",
    ("ZZ Persist Check",),
).fetchall()
print(rows)
conn.close()
PY
```

Expected: the holder row is present both before and after `down/up`.
`docker compose down` preserves data in the mounted `/app/data/assettrack.db`.
Data is wiped only if you explicitly remove volumes (for example `docker compose down -v`).

---

## 🪟 Windows (WSL2 + Docker Desktop)

### Recommended Windows Setup

* Windows 11
* WSL2 installed (Ubuntu recommended)
* Docker Desktop installed
* WSL integration enabled in Docker Desktop settings

### Clone Inside WSL (Not `/mnt/c/...`)

```
cd ~
git clone https://github.com/<your-org>/AssetTrack.git
cd AssetTrack
```

Running from `/mnt/c` can cause:

* Slow I/O
* Mount inconsistencies
* File permission edge cases

Keep the repository inside the Linux filesystem (`~`).

### Start the Application

```
docker compose up -d --build
```

Then open:

[http://localhost:8000](http://localhost:8000)

---

## 🔐 Security Posture

The container image is scanned using Trivy.

Current baseline:

* OS vulnerabilities: 0
* Python package vulnerabilities: 0
* LOW / MED / HIGH / CRIT: all zero

Latest readable scan report:

docs/security/trivy-readable.md

The reproducible scan command is documented inside that file.

---

## Operational Notes

* Root (`/`) routes to login
* Authenticated users land on dashboard
* All state transitions are logged
* No external services required
* No background jobs
* No hidden side effects

AssetTrack is intentionally boring.

That is a feature.

---

## Documentation

* [Operator Manual](docs/user-guide.md)

---

## Acknowledgements

AssetTrack was built through iterative reduction — removing accidental complexity while preserving operational integrity.

Thanks to:

* Open-source tooling focused on composability
* Field operators who value reliability over aesthetics
* Prior versions of this system that clarified what to eliminate
* @CyberJrod for early technical feedback and assumption pressure-testing
