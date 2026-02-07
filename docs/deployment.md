<!-- docs/deployment.md -->

# Deployment

This doc explains how to run AssetTrack in a repeatable way for real-world use.

## What you need

- Git
- Python 3.12+
- macOS, Linux, or Windows
- (Optional) Docker

## Quick start (local)

### macOS / Linux

1) Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2) Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

3) Run the app:

```bash
python3 -m assettrack
```

## Windows notes

AssetTrack supports running on Windows in two ways.

### Option A — Native Windows Python (recommended)

1. Install Python 3.12+ from python.org  
   During install, check **“Add Python to PATH”**.

2. Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

3. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

4. Run the app:

```powershell
python -m assettrack
```

### Option B — Windows Subsystem for Linux (WSL)

1. Install WSL with a Linux distro (Ubuntu is fine).
2. Follow the **macOS / Linux** instructions above inside WSL.

## Data storage

* AssetTrack uses SQLite.
* The database file location is configured by the app.
* Treat the database file like a business record: back it up and control access.

## Common operations

### Start a fresh local run

* Stop the app
* Remove the local database file (only if you mean it)
* Start the app again

### Upgrade workflow

* Pull latest `main`
* Rebuild dependencies (`pip install -r requirements.txt`)
* Run the app
* Confirm the database starts cleanly (and migrations apply cleanly if you add them later)

## Docker (optional)

If you run AssetTrack using Docker:

* Build the image
* Run the container
* Mount a volume for the SQLite database so data persists

(Exact commands live in the README or docker documentation.)

## Troubleshooting

* If dependencies won’t install: confirm you’re inside `.venv`
* If Python version is wrong: run `python --version` (Windows) or `python3 --version` (macOS/Linux)
* If the app won’t start: run `python -m compileall .` to catch syntax issues
