# assettrack/intake/app.py (keyboard wedge, UI)
"""
Issue 4-1: Local Intake UI (Keyboard Wedge) — proof of capture.

Feynman-brief:
- Scanner acts like a keyboard.
- Browser input box receives the "typed" barcode + Enter.
- We store scans in an in-memory list (queue) and echo them back.
"""

from __future__ import annotations
from flask import Flask, request, render_template, session, redirect
from assettrack.intake.to_ingest import scan_to_ingest_row
from assettrack.intake.scan import Scan
from assettrack.ingest.validator import validate_rows
import os
import time

app = Flask(__name__)
app.secret_key = os.getenv("ASSETTRACK_SECRET_KEY", "dev-not-secret")

# In-memory only: wiped on restart (by design for Issue 4-1).
SCAN_QUEUE: list[Scan] = []
INTAKE_PASSCODE = os.getenv("ASSETTRACK_INTAKE_CODE")
INTAKE_TIMEOUT_SECONDS = int(os.getenv("ASSETTRACK_INTAKE_TIMEOUT_SECONDS", "300"))  # 5 minutes default

def touch_session() -> None:
    session["last_seen"] = int(time.time())

def sanitize_scan(raw: str) -> str:
    """
    Keep only letters and numbers.
    Anything else (tabs/newlines/suffix junk) is dropped.
    """
    return "".join(ch for ch in raw if ch.isalnum())

def auth_ok(submitted: str | None) -> bool:
    """
    Minimal auth gate.
    If no passcode is set, auth is disabled.
    """
    if not INTAKE_PASSCODE:
        return True
    return submitted == INTAKE_PASSCODE

def seconds_since_last_seen() -> int | None:
    last_seen = session.get("last_seen")
    if not last_seen:
        return None
    now = int(time.time())
    return max(0, now - int(last_seen))

@app.route("/", methods=["GET", "POST"])
def intake():
    latest = ""

    # If no passcode is set, auth is disabled.
    if not INTAKE_PASSCODE:
        authed = True
    else:
        authed = bool(session.get("authed", False))
    
    # Auto-lock after inactivity.
    if INTAKE_PASSCODE and authed:
        last_seen = int(session.get("last_seen", 0))
        now = int(time.time())
        if last_seen and (now - last_seen) > INTAKE_TIMEOUT_SECONDS:
            session.pop("authed", None)
            session.pop("last_seen", None)
            authed = False
        else:
            touch_session()

    # Handle unlock attempt
    if request.method == "POST" and INTAKE_PASSCODE and "access_code" in request.form:
        submitted_code = request.form.get("access_code")
        if auth_ok(submitted_code):
            session["authed"] = True
            touch_session()
        return redirect("/")

    # Handle scan / clear
    if request.method == "POST" and authed:
        action = request.form.get("action", "scan")

        if action == "clear":
            SCAN_QUEUE.clear()
        else:
            raw = request.form.get("scan_text", "")
            scan = sanitize_scan(raw)
            if scan:
                record = Scan.now(asset_tag=scan)
                SCAN_QUEUE.append(record)
                latest = record.asset_tag

    return render_template(
      "index.html",
      latest=latest,
      queue=SCAN_QUEUE,
      queue_len=len(SCAN_QUEUE),
      authed=authed,
      auth_enabled=bool(INTAKE_PASSCODE),
  )

@app.route("/preview", methods=["GET"])
def preview():
    rows = [scan_to_ingest_row(s) for s in SCAN_QUEUE]
    return {"count": len(rows), "rows": rows}

@app.get("/preview/validate")
def preview_validate():
    parsed_rows = [
        {"row_number": idx + 1, "data": scan_to_ingest_row(s)}
        for idx, s in enumerate(SCAN_QUEUE)
    ]

    result = validate_rows(parsed_rows)

    return {
        "row_count": len(parsed_rows),
        "valid": bool(result.get("valid")) if isinstance(result, dict) else False,
        "result": result,
    }

@app.get("/lock")
def lock():
    session.pop("authed", None)
    session.pop("last_seen", None)
    return redirect("/")

if __name__ == "__main__":
    # Local dev run (container wiring comes later).
    app.run(host="127.0.0.1", port=8000, debug=True)