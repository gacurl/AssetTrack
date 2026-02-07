# assettrack/intake/app.py
"""
Issue 4-1: Local Intake UI (Keyboard Wedge) — proof of capture.

Feynman-brief:
- Scanner acts like a keyboard.
- Browser input box receives the "typed" barcode + Enter.
- We store scans in an in-memory list (queue) and echo them back.
"""

from __future__ import annotations

import os
import time
from typing import Optional

from flask import Flask, redirect, render_template, request, session

from assettrack.ingest.validator import validate_rows
from assettrack.intake.scan import Scan
from assettrack.intake.to_ingest import scan_to_ingest_row


app = Flask(__name__)
app.secret_key = os.getenv("ASSETTRACK_SECRET_KEY", "dev-not-secret")

# In-memory only: wiped on restart
SCAN_QUEUE: list[Scan] = []

INTAKE_PASSCODE = os.getenv("ASSETTRACK_INTAKE_CODE")
INTAKE_TIMEOUT_SECONDS = int(os.getenv("ASSETTRACK_INTAKE_TIMEOUT_SECONDS", "300"))  # default 5 min


# Helper functions

def now_seconds() -> int:
    return int(time.time())


def touch_session() -> None:
    session["last_seen"] = now_seconds()


def sanitize_scan(raw: str) -> str:
    """Keep only letters and numbers; drop tabs/newlines/suffix junk."""
    return "".join(ch for ch in raw if ch.isalnum())


def auth_enabled() -> bool:
    return bool(INTAKE_PASSCODE)


def is_authed() -> bool:
    """If no passcode is set, auth is disabled (always authed)."""
    return True if not auth_enabled() else bool(session.get("authed", False))


def set_authed(value: bool) -> None:
    if value:
        session["authed"] = True
        touch_session()
    else:
        session.pop("authed", None)
        session.pop("last_seen", None)


def auth_ok(submitted: str | None) -> bool:
    if not auth_enabled():
        return True
    return submitted == INTAKE_PASSCODE


def enforce_inactivity_timeout() -> bool:
    """
    If authed, lock after inactivity.
    Returns the post-enforcement authed state.
    """
    if not (auth_enabled() and is_authed()):
        return is_authed()

    last_seen = session.get("last_seen")
    if last_seen is None:
        # Authed but missing last_seen: initialize.
        touch_session()
        return True

    elapsed = now_seconds() - int(last_seen)
    if elapsed > INTAKE_TIMEOUT_SECONDS:
        set_authed(False)
        return False

    # Still valid: refresh activity.
    touch_session()
    return True


def seconds_since_last_seen() -> Optional[int]:
    last_seen = session.get("last_seen")
    if last_seen is None:
        return None
    return max(0, now_seconds() - int(last_seen))

# Route handlers

@app.route("/", methods=["GET", "POST"])
def intake():
    latest = ""

    # Handle unlock attempt first (works even when currently locked).
    if request.method == "POST" and auth_enabled() and "access_code" in request.form:
        submitted_code = request.form.get("access_code")
        if auth_ok(submitted_code):
            set_authed(True)
        return redirect("/")

    # Determine auth state and enforce timeout for authed sessions.
    authed = enforce_inactivity_timeout()

    # Handle scan / clear only when authed.
    if request.method == "POST" and authed:
        action = request.form.get("action", "scan")

        if action == "clear":
            SCAN_QUEUE.clear()
            touch_session()
        else:
            raw = request.form.get("scan_text", "")
            scan = sanitize_scan(raw)
            if scan:
                record = Scan.now(asset_tag=scan)
                SCAN_QUEUE.append(record)
                latest = record.asset_tag
                touch_session()

        return redirect("/")

    # View model for template.
    timeout_seconds = INTAKE_TIMEOUT_SECONDS
    last_seen_age_seconds = seconds_since_last_seen()

    # If unlocked/auth-disabled, never allow the UI to show a blank "Last activity".
    if authed and last_seen_age_seconds is None:
        last_seen_age_seconds = 0

    return render_template(
        "index.html",
        latest=latest,
        queue=SCAN_QUEUE,
        queue_len=len(SCAN_QUEUE),
        authed=authed,
        auth_enabled=auth_enabled(),
        timeout_seconds=timeout_seconds,
        last_seen_age_seconds=last_seen_age_seconds,
    )


@app.get("/preview")
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
    set_authed(False)
    return redirect("/")


if __name__ == "__main__":
    # Local dev run (and container run).
    app.run(host="0.0.0.0", port=8000, debug=True)