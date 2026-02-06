# assettrack/intake/app.py (keyboard wedge, UI)
"""
Issue 4-1: Local Intake UI (Keyboard Wedge) — proof of capture.

Feynman-brief:
- Scanner acts like a keyboard.
- Browser input box receives the "typed" barcode + Enter.
- We store scans in an in-memory list (queue) and echo them back.
"""

from __future__ import annotations
from flask import Flask, request, render_template_string, session, redirect
from assettrack.intake.to_ingest import scan_to_ingest_row
from assettrack.intake.scan import Scan
import os

app = Flask(__name__)
app.secret_key = os.getenv("ASSETTRACK_SECRET_KEY", "dev-not-secret")

# In-memory only: wiped on restart (by design for Issue 4-1).
SCAN_QUEUE: list[Scan] = []

def sanitize_scan(raw: str) -> str:
    """
    Keep only letters and numbers.
    Anything else (tabs/newlines/suffix junk) is dropped.
    """
    return "".join(ch for ch in raw if ch.isalnum())

INTAKE_PASSCODE = os.getenv("ASSETTRACK_INTAKE_CODE")

def auth_ok(submitted: str | None) -> bool:
    """
    Minimal auth gate.
    If no passcode is set, auth is disabled.
    """
    if not INTAKE_PASSCODE:
        return True
    return submitted == INTAKE_PASSCODE

PAGE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>AssetTrack Intake</title>
    <style>
      body { font-family: system-ui, -apple-system, Arial, sans-serif; margin: 2rem; }
      .row { margin: 0.75rem 0; }
      input[type="text"] { width: 100%; max-width: 520px; padding: 0.6rem; font-size: 1rem; }
      button { padding: 0.6rem 1rem; font-size: 1rem; margin-left: 0.25rem; }
      .card { margin-top: 1rem; padding: 1rem; border: 1px solid #ddd; border-radius: 10px; max-width: 820px; }
      code { background: #f6f6f6; padding: 0.15rem 0.3rem; border-radius: 4px; }
    </style>
  </head>
  <body>
    <h1>AssetTrack Intake</h1>
    {% if auth_enabled and authed %}
      <p><a href="/lock">Lock</a></p>
    {% endif %}

    <div class="card">
      <p><strong>How to use:</strong> click the box once, then scan. The scanner “types” and hits Enter.</p>
      <p><a href="/preview" target="_blank">Preview ingest rows (JSON)</a></p>

      {% if auth_enabled and not authed %}
        <form method="post">
          <input type="password" name="access_code" placeholder="Access code" autofocus />
          <button type="submit">Unlock</button>
        </form>
      {% else %}
        <form class="row" method="post" action="/">
          <input
            type="text"
            name="scan_text"
            placeholder="Scan here..."
            autofocus
            autocomplete="off"
          />
          <button type="submit">Submit</button>
          <button type="submit" name="action" value="clear">Clear queue</button>
        </form>
      {% endif %}
    </div>

    <div class="card">
      <h2>Latest scan</h2>
      <p><code>{{ latest }}</code></p>
    </div>

    <div class="card">
      <h2>Queue ({{ queue_len }})</h2>
      <ul>
        {% for s in queue %}
          <li><code>{{ s.asset_tag }}</code></li>
        {% endfor %}
      </ul>
    </div>
  </body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def intake():
    latest = ""

    # If no passcode is set, auth is disabled.
    if not INTAKE_PASSCODE:
        authed = True
    else:
        authed = bool(session.get("authed", False))

    # Handle unlock attempt
    if request.method == "POST" and INTAKE_PASSCODE and "access_code" in request.form:
        submitted_code = request.form.get("access_code")
        if auth_ok(submitted_code):
            session["authed"] = True
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

    return render_template_string(
        PAGE,
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

@app.get("/lock")
def lock():
    session.pop("authed", None)
    return redirect("/")

if __name__ == "__main__":
    # Local dev run (container wiring comes later).
    app.run(host="127.0.0.1", port=8000, debug=True)