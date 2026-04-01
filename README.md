
# ⚠️ Disclaimer (Not Government Endorsed)

This software is an independent tool and is **not affiliated with, endorsed by, or sponsored by** the U.S. Department of War (DoW), U.S. Department of Defense (DoD), or any other government agency. Use of this software does **not** imply compliance with or substitution for official DoW/DoD policies, forms, or procedures. **You are responsible** for verifying accuracy and complying with all applicable regulations and for using official systems where required.

---

# AssetTrack

## Project Overview

AssetTrack is an offline-first asset custody tracking system designed for field deployment.

The system maintains a complete append-only audit trail of asset movement while providing simple workflows for issuing, returning, and managing assets.

AssetTrack runs as a Dockerized web application with a persistent SQLite database.

---

## System Model

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

## Quick Start

Clone the repository and start the system:

```bash
git clone https://github.com/gacurl/AssetTrack.git
cd AssetTrack
docker compose up -d --build
```

On a first run with no database file, AssetTrack initializes the approved SQLite schema automatically in the mounted `/app/data/assettrack.db` path before the web app starts.

Open the application:

`http://localhost:8000`

If this is a fresh database with no users yet, bootstrap the first admin at:

`http://localhost:8000/bootstrap/admin`

## Standard Inventory Import Workflow

Run inventory import inside the running Docker container so it uses the image's installed dependencies and the mounted persistent SQLite database:

```bash
docker compose up -d --build
./scripts/import_inventory_docker.sh
```

Equivalent direct command:

```bash
docker compose exec -T assettrack python -m scripts.import_inventory
```

This is the supported import path for `.xlsx` inventory loads. Do not rely on host-installed `pandas` or `openpyxl`.

## Release Documentation

AssetTrack includes a full release documentation package.

- Deployment guide: `docs/release/deployment.md`
- User manual: `docs/release/user-manual.md`
- Smoke test: `docs/release/smoke-test.md`
- Troubleshooting: `docs/release/troubleshooting.md`
- Security report: `docs/release/security-report.md`
- Release notes: `docs/release/release-notes.md`

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

## Verifying Docker Persistence

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

## Windows Notes

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

## Security

The MVP release includes a clean Trivy security scan.

Detailed scan results and remediation notes are available here:

`docs/security/trivy-readable.md`

## Project Status

Current release:

`v0.1.0-mvp`

Key characteristics:

- Offline-first architecture
- Append-only event history
- Audit-safe asset state transitions
- Docker-based deployment
- Persistent SQLite database

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

- Release documentation index: `docs/release/`
- Legacy operator manual: `docs/user-guide.md`

---

## Acknowledgements

AssetTrack was built through iterative reduction — removing accidental complexity while preserving operational integrity.

Thanks to:

* Open-source tooling focused on composability
* Field operators who value reliability over aesthetics
* Prior versions of this system that clarified what to eliminate
* @CyberJrod for early technical feedback and assumption pressure-testing
