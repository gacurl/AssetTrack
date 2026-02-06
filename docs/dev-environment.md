# Developer Environment (Offline‑Safe)

This project is designed to run **without internet access** once dependencies are vendored. This document captures the rules and fixes that prevent common macOS + Homebrew + Python failures.

---

## Python & Virtual Environment Rules (macOS)

**Authoritative rule:** always use the Python inside `.venv`.

Do **not** rely on shell aliases like `python3` or `pip`.

Use these forms **every time**:
- `./.venv/bin/python ...`
- `./.venv/bin/python -m pip ...`

### Verify you are using the venv Python

```
./.venv/bin/python --version
```

If `which python3` points to `/usr/local/bin/python3` or `/opt/homebrew/...`, that is **system Python**, not the venv.

---

## Offline Dependency Workflow (Pinned + Vendored)

AssetTrack installs Python dependencies **without reaching the internet**.

### 1. Pin dependencies

All runtime dependencies must be pinned in `requirements.txt`.

Example:
```
Flask==3.0.2
```

---

### 2. Build wheels using the venv Python

**Critical rule:** wheels must be built with the *same Python* that will install them.

```
rm -rf vendor/wheels
mkdir -p vendor/wheels
./.venv/bin/python -m pip download --dest vendor/wheels -r requirements.txt
```

This avoids wheel tag mismatches (e.g. `cp313` vs `cp312`).

---

### 3. Install from vendored wheels (offline)

```
./.venv/bin/python -m pip install --no-index --find-links vendor/wheels -r requirements.txt
```

This must succeed **without internet access**.

---

## Runtime Verification (Authoritative)

`compileall` only checks syntax. It does **not** prove runtime correctness.

### Required runtime check

```
./.venv/bin/python assettrack/intake/app.py
```

Expected result:
- Flask starts
- App runs at `http://127.0.0.1:8000`
- Typed or scanned input echoes back in the UI

Only this confirms a working environment.

---

## Common Failure Modes & Fixes

### `externally-managed-environment`

Cause:
- pip is targeting Homebrew/system Python (PEP 668)

Fix:
- Use `./.venv/bin/python -m pip ...`
- Never install packages into system Python

---

### `No matching distribution found` (MarkupSafe / Jinja2)

Cause:
- Wheels were built for a different Python version than the venv

Fix:
- Rebuild `vendor/wheels` using the venv Python

---

## Design Intent

- `.venv` isolates all Python behavior
- `vendor/wheels/` guarantees offline installs
- Runtime verification is explicit and repeatable

This document exists so future work does **not** rediscover these constraints the hard way.

