
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
* Bind-mounted host-directory persistence
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
* Docker-based deployment with bind-mounted host-directory durability

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
./scripts/bootstrap_docker.sh
```

The bootstrap script delegates startup and persistent data initialization to Docker Compose.

Docker Compose also supports the direct startup command:

```bash
docker compose up -d --build
```

On a fresh clone with no `./data` directory, Compose may create the host bind-mount directory as root-owned. AssetTrack handles that with a one-shot `assettrack-data-init` service that runs before the web app, sets `/app/data` to UID `100` and GID `101`, and uses directory mode `0750`. The final `assettrack` web service still runs as the non-root `assettrack` user.

On a first run with no database file, AssetTrack initializes the approved SQLite schema automatically in the mounted `/app/data/assettrack.db` path before the web app starts.

Open the application:

`http://localhost:8000`

If this is a fresh database with no users yet, bootstrap the first admin at:

`http://localhost:8000/bootstrap/admin`

## Fixed-Workbook Inventory Bootstrap

For the fixed `.xlsx` bootstrap workbook at `data/import/BQ26_ETP.xlsx`, run the inventory importer inside the running Docker container so it uses the image's installed dependencies and the mounted persistent SQLite database:

```bash
./scripts/bootstrap_docker.sh
./scripts/import_inventory_docker.sh
```

Equivalent direct command:

```bash
docker compose exec -T assettrack python -m scripts.import_inventory
```

This is a fixed-workbook/bootstrap path. Normal CSV/XLSX asset imports use Admin Tools -> Import Assets for Laptop, Switch, and Router records. Do not rely on host-installed `pandas` or `openpyxl` for the bootstrap workbook.

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

AssetTrack uses a host bind mount for persistent Docker data:

```
./data:/app/data
```

This means:

* Database survives container restarts
* Database survives `docker compose down`
* Data remains in the repo-local `./data` directory unless you remove it yourself

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
./scripts/bootstrap_docker.sh
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
Data is wiped only if you explicitly remove the repo-local `./data` contents.

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
./scripts/bootstrap_docker.sh
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
