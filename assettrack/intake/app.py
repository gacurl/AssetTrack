# assettrack/intake/app.py (keyboard wedge, UI)
"""
Issue 4-1: Local Intake UI (Keyboard Wedge) — proof of capture.

Feynman-brief:
- Scanner acts like a keyboard.
- Browser input box receives the "typed" barcode + Enter.
- We store scans in an in-memory list (queue) and echo them back.
"""

from __future__ import annotations
from flask import Flask, request, render_template_string

import os

app = Flask(__name__)

# In-memory only: wiped on restart (by design for Issue 4-1).
SCAN_QUEUE: list[str] = []

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

    <div class="card">
      <p><strong>How to use:</strong> click the box once, then scan. The scanner “types” and hits Enter.</p>

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
          <li><code>{{ s }}</code></li>
        {% endfor %}
      </ul>
    </div>
  </body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def intake():
    latest = ""
    authed = True

    if INTAKE_PASSCODE:
        submitted_code = request.form.get("access_code")
        authed = auth_ok(submitted_code)

    if request.method == "POST" and authed:
        action = request.form.get("action", "scan")

        if action == "clear":
            SCAN_QUEUE.clear()
        else:
            raw = request.form.get("scan_text", "")
            scan = sanitize_scan(raw)
            if scan:
                SCAN_QUEUE.append(scan)
                latest = scan

    return render_template_string(
        PAGE,
        latest=latest,
        queue=SCAN_QUEUE,
        queue_len=len(SCAN_QUEUE),
        authed=authed,
        auth_enabled=bool(INTAKE_PASSCODE),
    )


if __name__ == "__main__":
    # Local dev run (container wiring comes later).
    app.run(host="127.0.0.1", port=8000, debug=True)