# ---------------------------------------------------------------------------------------
# DISCLAIMER
# This software is an independent tool created by the author and is not affiliated with,
# endorsed by, or sponsored by the U.S. Department of Defense (DoD), the U.S. Army, or
# any other government agency. Use of this software does not imply compliance with or
# substitution for official DoD/Army policies, forms, or procedures. Users are solely
# responsible for verifying accuracy, ensuring compliance with all applicable regulations,
# and using official, authorized systems and processes where required.
#
# Author: Joe Rodrigues
# Contact: Joseph.Rodrigues@NetworksEncrypted.com
#
# ---------------------------------------------------------------------------------------

"""
Hand Receipt Manager (DA Form 2062, DEC 2023)

New in this version:
- Deletion is allowed ONLY for items that are "On Hand".
- When deleting:
  * The app shows which selected serials are not On Hand (e.g., Issued to X) and skips them.
  * Only On-Hand items (if any) move to the Recycle Bin.
- Recycle Bin tab lets you Restore or Permanently Delete soft-deleted items.

Other features:
- Inventory with managed dropdowns (Model/Category/Box) persisted in inventory_lists.json
- Add many serials at once (comma-separated or one-per-line)
- CSV import/export (export excludes deleted; import can revive soft-deleted serials)
- Issue & Return tabs (Issue does NOT generate PDF)
- Issued Items tab: view by custodian, store Issued by & Contact, generate DA 2062
- DA 2062 overlay on a flattened template; 10 serials per row (4 + 6); pagination; calibration page
- Calibration tab with explanations, saved to da2062_layout.json

Dependencies:
  python -m pip install --upgrade pypdf reportlab pandas openpyxl cryptography
"""

import os
import io
import sys
import re
import json
import sqlite3
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime
from collections import defaultdict

# ---- startup guard
def _startup_error_dialog():
    try:
        import tkinter as _tk
        from tkinter import messagebox as _mb
        r = _tk.Tk(); r.withdraw()
        _mb.showerror("Startup error", traceback.format_exc())
        try: r.destroy()
        except Exception: pass
    except Exception:
        print(traceback.format_exc(), file=sys.stderr)

# ---- GUI
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog, simpledialog
except Exception:
    _startup_error_dialog()
    raise

# ---- PDF & data deps
try:
    from pypdf import PdfReader as PyPdfReader, PdfWriter as PyPdfWriter
except Exception:
    messagebox.showerror("Missing dependency", "Install pypdf:\n\npython -m pip install pypdf")
    raise

try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import simpleSplit
except Exception:
    messagebox.showerror("Missing dependency", "Install reportlab:\n\npython -m pip install reportlab")
    raise

try:
    import pandas as pd
except Exception:
    messagebox.showerror("Missing dependency",
                         "Excel import needs 'pandas' + 'openpyxl':\n\npython -m pip install pandas openpyxl")
    raise

# ---- bundling helper
def resource_path(rel_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.join(os.path.dirname(__file__), rel_path)

# ---- config
DB_FILE = "inventory.db"
TEMPLATE_PDF = resource_path("DA2062_flat.pdf")

STATUS_ON_HAND = "On Hand"
STATUS_ISSUED  = "Issued"

SERIALS_FIRST_LINE = 4
SERIALS_SECOND_LINE = 6
SERIALS_PER_ROW = SERIALS_FIRST_LINE + SERIALS_SECOND_LINE

LAYOUT_FILE = "da2062_layout.json"
INVENTORY_LISTS_FILE = "inventory_lists.json"

DEFAULT_INVENTORY_LISTS = {"models": [], "boxes": [], "categories": []}

@dataclass
class LayoutConfig:
    font_name: str = "Helvetica"
    font_size: float = 9.0
    font_size_hdr: float = 10.0
    x_from: float = 260.0
    y_from: float = 590.0
    x_to: float   = 710.0
    y_to: float   = 590.0
    to_contact_offset: float = 12.0
    x_page_right: float = 575.0
    y_identifier: float = 717.0
    item_desc_x: float = 226.0
    qty_auth_x: float  = 591.0
    item_start_y_first: float = 493.0
    item_start_y_next: float  = 640.0
    line_spacing: float = 23.0
    second_line_offset: float = 11.0
    rows_first: int = 16
    rows_next: int  = 20

def load_layout() -> "LayoutConfig":
    path = resource_path(LAYOUT_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return LayoutConfig(**{**asdict(LayoutConfig()), **data})
        except Exception:
            return LayoutConfig()
    return LayoutConfig()

def save_layout(cfg: "LayoutConfig"):
    with open(LAYOUT_FILE, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)

def load_inventory_lists() -> dict:
    path = resource_path(INVENTORY_LISTS_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("models", [])
            data.setdefault("boxes", [])
            data.setdefault("categories", [])
            return data
        except Exception:
            return DEFAULT_INVENTORY_LISTS.copy()
    return DEFAULT_INVENTORY_LISTS.copy()

def save_inventory_lists(data: dict):
    cleaned = {
        "models": sorted(set(map(str, data.get("models", [])))),
        "boxes":  sorted(set(map(str, data.get("boxes",  [])))),
        "categories": sorted(set(map(str, data.get("categories",  []))))
    }
    with open(INVENTORY_LISTS_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2)

LCFG = load_layout()
INVLISTS = load_inventory_lists()

# ---- DB
def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL,
            category TEXT NOT NULL,
            box_no TEXT,
            serial TEXT UNIQUE NOT NULL,
            asset_tag TEXT,
            status TEXT NOT NULL,
            custodian TEXT,
            updated_at TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            deleted_reason TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_dt TEXT NOT NULL,
            issued_from TEXT NOT NULL,
            issued_to TEXT NOT NULL,
            doc_no TEXT,
            remarks TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS issue_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id INTEGER NOT NULL,
            model TEXT NOT NULL,
            category TEXT NOT NULL,
            serial TEXT NOT NULL,
            asset_tag TEXT,
            FOREIGN KEY(issue_id) REFERENCES issues(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS custodian_meta (
            custodian TEXT PRIMARY KEY,
            contact TEXT,
            issued_from TEXT,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit(); conn.close()

def _table_columns(conn, table):
    cur = conn.cursor(); cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}

def migrate_db():
    conn = sqlite3.connect(DB_FILE)
    try:
        cur = conn.cursor()
        cols = _table_columns(conn, "issues")
        if "doc_no" not in cols:
            cur.execute("ALTER TABLE issues ADD COLUMN doc_no TEXT")
        if "remarks" not in cols:
            cur.execute("ALTER TABLE issues ADD COLUMN remarks TEXT")

        cols_inv = _table_columns(conn, "inventory")
        if "is_deleted" not in cols_inv:
            cur.execute("ALTER TABLE inventory ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
        if "deleted_at" not in cols_inv:
            cur.execute("ALTER TABLE inventory ADD COLUMN deleted_at TEXT")
        if "deleted_reason" not in cols_inv:
            cur.execute("ALTER TABLE inventory ADD COLUMN deleted_reason TEXT")

        conn.commit()
    finally:
        conn.close()

def with_conn(fn):
    def wrap(*a, **k):
        conn = sqlite3.connect(DB_FILE)
        try:
            out = fn(conn, *a, **k)
            conn.commit()
            return out
        finally:
            conn.close()
    return wrap

@with_conn
def db_add_item(conn, model, category, box_no, serial, asset_tag=None):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO inventory (model, category, box_no, serial, asset_tag, status, custodian, updated_at, is_deleted)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, (model.strip(), category.strip(), (box_no or "").strip() or None,
          serial.strip(), (asset_tag or "").strip() or None,
          STATUS_ON_HAND, None, now_iso()))
    return cur.lastrowid

# --- Soft delete ONLY On-Hand items
@with_conn
def db_soft_delete_onhand_by_serials(conn, serials, reason=None):
    """
    Soft-delete ONLY items that are currently On Hand.
    Returns (moved_count, skipped_serials) where skipped_serials are not On Hand or already deleted.
    """
    if not serials:
        return 0, []

    q = ",".join("?" for _ in serials)
    cur = conn.cursor()
    # On-hand, not deleted
    cur.execute(f"""
        SELECT serial
          FROM inventory
         WHERE serial IN ({q})
           AND is_deleted=0
           AND status=?
    """, (*serials, STATUS_ON_HAND))
    onhand_serials = [row[0] for row in cur.fetchall()]
    onhand_set = set(onhand_serials)
    skipped = [s for s in serials if s not in onhand_set]

    moved = 0
    if onhand_serials:
        q2 = ",".join("?" for _ in onhand_serials)
        cur.execute(f"""
            UPDATE inventory
               SET is_deleted=1,
                   deleted_at=?,
                   deleted_reason=?,
                   updated_at=?
             WHERE serial IN ({q2})
               AND is_deleted=0
               AND status=?
        """, (now_iso(), (reason or None), now_iso(), *onhand_serials, STATUS_ON_HAND))
        moved = cur.rowcount

    return moved, skipped

@with_conn
def db_restore_by_serials(conn, serials):
    if not serials: return 0
    q = ",".join("?" for _ in serials)
    cur = conn.cursor()
    cur.execute(f"""
        UPDATE inventory
           SET is_deleted=0,
               deleted_at=NULL,
               deleted_reason=NULL,
               updated_at=?
         WHERE serial IN ({q}) AND is_deleted=1
    """, (now_iso(), *serials))
    return cur.rowcount

@with_conn
def db_purge_by_serials(conn, serials):
    if not serials: return 0
    q = ",".join("?" for _ in serials)
    cur = conn.cursor()
    cur.execute(f"DELETE FROM inventory WHERE serial IN ({q}) AND is_deleted=1", (*serials,))
    return cur.rowcount

@with_conn
def db_get_status_by_serials(conn, serials):
    if not serials:
        return {}
    q = ",".join("?" for _ in serials)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT serial, status, COALESCE(custodian,'')
          FROM inventory
         WHERE serial IN ({q})
    """, (*serials,))
    out = {}
    for s, st, cust in cur.fetchall():
        out[s] = {"status": st, "custodian": cust}
    return out

@with_conn
def db_list_inventory(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT id, model, category, COALESCE(box_no,''), serial, COALESCE(asset_tag,''), status, COALESCE(custodian,''), updated_at
          FROM inventory
         WHERE is_deleted=0
         ORDER BY model, serial
    """)
    return cur.fetchall()

@with_conn
def db_list_recycle(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT id, model, category, COALESCE(box_no,''), serial, COALESCE(asset_tag,''), status, COALESCE(custodian,''),
               COALESCE(deleted_reason,''), COALESCE(deleted_at,''), updated_at
          FROM inventory
         WHERE is_deleted=1
         ORDER BY deleted_at DESC, model, serial
    """)
    return cur.fetchall()

@with_conn
def db_export_csv(conn, path):
    import csv
    cur = conn.cursor()
    cur.execute("""
        SELECT model, category, COALESCE(box_no,''), serial, COALESCE(asset_tag,''), status, COALESCE(custodian,''), updated_at
          FROM inventory
         WHERE is_deleted=0
         ORDER BY model, serial
    """)
    rows = cur.fetchall()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Model","Category","Box #","Serial Number","Asset Tag #","Status","Custodian","Updated At"])
        for r in rows: w.writerow(r)

@with_conn
def db_import_csv(conn, path):
    import csv
    cur = conn.cursor(); added = 0
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        required = {"Model","Category","Serial Number"}
        if not required.issubset(set(r.fieldnames or [])):
            raise ValueError(f"CSV must include at least {required}")
        for row in r:
            model = (row.get("Model") or "").strip()
            category = (row.get("Category") or "").strip()
            serial = (row.get("Serial Number") or "").strip()
            if not (model and category and serial): continue
            box = (row.get("Box #") or "").strip() or None
            asset = (row.get("Asset Tag #") or "").strip() or None
            try:
                cur.execute("""
                    INSERT INTO inventory (model, category, box_no, serial, asset_tag, status, custodian, updated_at, is_deleted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (model, category, box, serial, asset, STATUS_ON_HAND, None, now_iso()))
                added += 1
            except sqlite3.IntegrityError:
                # If it exists but was soft-deleted, undelete and update fields
                cur.execute("""
                    UPDATE inventory
                       SET model=?,
                           category=?,
                           box_no=?,
                           asset_tag=?,
                           status=?,
                           custodian=NULL,
                           updated_at=?,
                           is_deleted=0,
                           deleted_at=NULL,
                           deleted_reason=NULL
                     WHERE serial=? 
                """, (model, category, box, asset, STATUS_ON_HAND, now_iso(), serial))
                if cur.rowcount > 0:
                    added += 1
    return added

@with_conn
def db_find_onhand_by_serials(conn, serials):
    if not serials: return []
    q = ",".join("?" for _ in serials)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT id, model, category, COALESCE(asset_tag,''), serial
          FROM inventory
         WHERE serial IN ({q}) AND status=? AND is_deleted=0
    """, (*[s.strip() for s in serials], STATUS_ON_HAND))
    return cur.fetchall()

@with_conn
def db_find_issued_by_serials(conn, serials):
    if not serials: return []
    q = ",".join("?" for _ in serials)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT id, model, category, COALESCE(asset_tag,''), serial, COALESCE(custodian,'')
          FROM inventory
         WHERE serial IN ({q}) AND status=? AND is_deleted=0
    """, (*[s.strip() for s in serials], STATUS_ISSUED))
    return cur.fetchall()

@with_conn
def db_upsert_custodian_meta(conn, custodian, contact, issued_from):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO custodian_meta (custodian, contact, issued_from, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(custodian) DO UPDATE SET
            contact=excluded.contact,
            issued_from=excluded.issued_from,
            updated_at=excluded.updated_at
    """, (custodian.strip(), (contact or "").strip(), (issued_from or "").strip(), now_iso()))

@with_conn
def db_get_custodian_meta(conn, custodian):
    cur = conn.cursor()
    cur.execute("SELECT contact, issued_from FROM custodian_meta WHERE custodian=?", (custodian.strip(),))
    row = cur.fetchone()
    if not row: return {"contact":"", "issued_from":""}
    return {"contact": row[0] or "", "issued_from": row[1] or ""}

@with_conn
def db_mark_issued(conn, items, issued_from, issued_to):
    cur = conn.cursor()
    issue_dt = now_iso()
    cur.execute("INSERT INTO issues (issue_dt, issued_from, issued_to) VALUES (?, ?, ?)",
                (issue_dt, issued_from.strip(), issued_to.strip()))
    issue_id = cur.lastrowid
    for it in items:
        cur.execute("""
            INSERT INTO issue_items (issue_id, model, category, serial, asset_tag)
            VALUES (?, ?, ?, ?, ?)
        """, (issue_id, it["model"], it["category"], it["serial"], it.get("asset_tag") or None))
        cur.execute("""
            UPDATE inventory SET status=?, custodian=?, updated_at=? 
             WHERE serial=? AND is_deleted=0
        """, (STATUS_ISSUED, issued_to.strip(), now_iso(), it["serial"]))
    return issue_id

@with_conn
def db_mark_returned(conn, serials):
    cur = conn.cursor(); updated = 0
    for s in serials:
        cur.execute("""
            UPDATE inventory
               SET status=?, custodian=NULL, updated_at=?
             WHERE serial=? AND status=? AND is_deleted=0
        """, (STATUS_ON_HAND, now_iso(), s.strip(), STATUS_ISSUED))
        updated += cur.rowcount
    return updated

@with_conn
def db_distinct_custodians_extended(conn):
    """Return (custodian, count, issued_from, contact)."""
    cur = conn.cursor()
    cur.execute("""
        WITH counts AS (
            SELECT COALESCE(custodian,'') AS cust, COUNT(*) AS cnt
              FROM inventory
             WHERE status=? AND is_deleted=0
             GROUP BY COALESCE(custodian,'')
        )
        SELECT c.cust,
               c.cnt,
               COALESCE(m.issued_from,'') AS issued_from,
               COALESCE(m.contact,'') AS contact
          FROM counts c
          LEFT JOIN custodian_meta m
            ON m.custodian = c.cust
         ORDER BY LOWER(c.cust) ASC
    """, (STATUS_ISSUED,))
    return cur.fetchall()

@with_conn
def db_list_issued_by_custodian(conn, custodian):
    cur = conn.cursor()
    cur.execute("""
        SELECT model, category, COALESCE(asset_tag,''), serial, updated_at
          FROM inventory
         WHERE status=? AND COALESCE(custodian,'')=? AND is_deleted=0
         ORDER BY model, serial
    """, (STATUS_ISSUED, custodian.strip()))
    return cur.fetchall()

@with_conn
def db_counts_by_status(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT status, COUNT(*) FROM inventory WHERE is_deleted=0 GROUP BY status
    """)
    data = dict(cur.fetchall())
    return {
        "on_hand": int(data.get(STATUS_ON_HAND, 0)),
        "issued": int(data.get(STATUS_ISSUED, 0)),
        "total": int(sum(data.values()))
    }

# ---- utils
def sanitize_serials_blob(text):
    parts = []
    for line in str(text).splitlines():
        for chunk in str(line).split(","):
            v = chunk.strip()
            if v: parts.append(v)
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p); out.append(p)
    return out

def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def build_rows_grouped_by_model(items):
    groups = defaultdict(list)
    for it in items:
        tag = (it.get("asset_tag") or "").strip()
        s = it["serial"].strip() + (f" [AT:{tag}]" if tag else "")
        groups[(it["model"], it["category"])].append(s)

    rows = []
    for (model, _cat), serials in groups.items():
        serials = sorted(serials)
        for start in range(0, len(serials), SERIALS_PER_ROW):
            pack = serials[start:start+SERIALS_PER_ROW]
            count = len(pack)
            if count <= SERIALS_FIRST_LINE:
                rows.append({"l1": f"{model} - S/N: {', '.join(pack)}", "l2": None, "qty": count})
            else:
                first = pack[:SERIALS_FIRST_LINE]
                rest  = pack[SERIALS_FIRST_LINE:SERIALS_FIRST_LINE+SERIALS_SECOND_LINE]
                rows.append({"l1": f"{model} - S/N: {', '.join(first)}",
                             "l2": f"S/N: {', '.join(rest)}" if rest else None,
                             "qty": count})
    return rows

def sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w\s.-]+", "", name.strip())
    name = re.sub(r"\s+", "_", name)
    return name or "Unknown"

# ---- PDF overlay helpers
def _template_reader():
    if not os.path.exists(TEMPLATE_PDF):
        raise FileNotFoundError(f"Template not found: {TEMPLATE_PDF}")
    r = PyPdfReader(TEMPLATE_PDF)
    if getattr(r, "is_encrypted", False):
        try:
            r.decrypt("")
        except Exception:
            pwd = simpledialog.askstring("PDF Password","Enter template password (blank for none):", show='*')
            if pwd is None:
                raise RuntimeError("PDF is encrypted and no password was provided.")
            if not r.decrypt(pwd):
                raise RuntimeError("Could not decrypt the template with the provided password.")
    return r

def _draw_header(c, meta, page_no, of_pages, first_page: bool):
    c.setFont(LCFG.font_name, LCFG.font_size_hdr)
    if first_page:
        if meta.get("issued_from"):
            c.drawString(LCFG.x_from, LCFG.y_from, meta["issued_from"])
        if meta.get("issued_to"):
            c.drawString(LCFG.x_to,   LCFG.y_to,   meta["issued_to"])
        contact = (meta.get("to_contact") or "").strip()
        if contact:
            max_w = 300
            lines = simpleSplit(f"Contact: {contact}", LCFG.font_name, LCFG.font_size_hdr, max_w)
            y = LCFG.y_to - LCFG.to_contact_offset
            for ln in lines[:2]:
                c.drawString(LCFG.x_to, y, ln)
                y -= (LCFG.font_size_hdr + 2)
    c.drawRightString(LCFG.x_page_right, LCFG.y_identifier, f"{page_no}/{of_pages}")

def _draw_rows(c, rows, start_y, rows_cap):
    y = start_y
    max_w = 430
    for r in rows[:rows_cap]:
        c.setFont(LCFG.font_name, LCFG.font_size)
        l1w = simpleSplit(r["l1"], LCFG.font_name, LCFG.font_size, max_w)
        c.drawString(LCFG.item_desc_x, y, l1w[0])
        if len(l1w) > 1:
            c.setFont(LCFG.font_name, LCFG.font_size - 1)
            c.drawString(LCFG.item_desc_x, y - (LCFG.font_size - 1) - 1, l1w[1])
            c.setFont(LCFG.font_name, LCFG.font_size)
        c.drawRightString(LCFG.qty_auth_x, y, str(r["qty"]))
        if r["l2"]:
            c.setFont(LCFG.font_name, LCFG.font_size)
            l2y = y - LCFG.second_line_offset
            l2w = simpleSplit(r["l2"], LCFG.font_name, LCFG.font_size, max_w)
            c.drawString(LCFG.item_desc_x, l2y, l2w[0])
            if len(l2w) > 1:
                c.setFont(LCFG.font_name, LCFG.font_size - 1)
                c.drawString(LCFG.item_desc_x, l2y - (LCFG.font_size - 1) - 1, l2w[1])
                c.setFont(LCFG.font_name)
        y -= LCFG.line_spacing

def _make_overlay_page(meta, rows, page_no, of_pages, first_page=True):
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    _draw_header(c, meta, page_no, of_pages, first_page=first_page)
    start_y = LCFG.item_start_y_first if first_page else LCFG.item_start_y_next
    cap = LCFG.rows_first if first_page else LCFG.rows_next
    _draw_rows(c, rows, start_y, cap)
    c.showPage(); c.save(); buf.seek(0)
    return buf

def _merge_overlay(base_page, overlay_buf):
    overlay_reader = PyPdfReader(overlay_buf)
    overlay_page = overlay_reader.pages[0]
    base_page.merge_page(overlay_page)

def render_2062_overlay(output_path, meta, rows):
    reader = _template_reader()
    if len(reader.pages) == 0:
        raise RuntimeError("Template has no pages.")
    tpl_first = reader.pages[0]
    tpl_next  = reader.pages[1] if len(reader.pages) > 1 else tpl_first

    first_rows = rows[:LCFG.rows_first]
    rest = rows[LCFG.rows_first:]
    next_groups = list(chunk_list(rest, LCFG.rows_next))
    total_pages = 1 + len(next_groups)

    writer = PyPdfWriter()
    writer.add_page(tpl_first)
    page = writer.pages[-1]
    buf = _make_overlay_page(meta, first_rows, 1, total_pages, first_page=True)
    _merge_overlay(page, buf)

    for idx, grp in enumerate(next_groups, start=2):
        writer.add_page(tpl_next)
        page = writer.pages[-1]
        buf = _make_overlay_page(meta, grp, idx, total_pages, first_page=False)
        _merge_overlay(page, buf)

    with open(output_path, "wb") as f:
        writer.write(f)

# ---- GUI
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Hand Receipt Manager (DA 2062 - DEC 2023)")
        self.geometry("1400x920")

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        self.inv_frame = ttk.Frame(nb)
        self.issue_frame = ttk.Frame(nb)
        self.return_frame = ttk.Frame(nb)
        self.issued_frame = ttk.Frame(nb)
        self.recycle_frame = ttk.Frame(nb)
        self.calib_frame = ttk.Frame(nb)
        nb.add(self.inv_frame, text="Inventory")
        nb.add(self.issue_frame, text="Issue")
        nb.add(self.return_frame, text="Return")
        nb.add(self.issued_frame, text="Issued Items")
        nb.add(self.recycle_frame, text="Recycle Bin")
        nb.add(self.calib_frame, text="Calibration")

        self._build_inventory_tab()
        self._build_issue_tab()
        self._build_return_tab()
        self._build_issued_tab()
        self._build_recycle_tab()
        self._build_calibration_tab()

        self.refresh_inventory()
        self.refresh_issued_lists()
        self.refresh_recycle()
        self.update_counts_labels()

    # -- Inventory tab
    def _build_inventory_tab(self):
        frm = self.inv_frame
        lf = ttk.LabelFrame(frm, text="Add Item(s)")
        lf.pack(side="top", fill="x", padx=8, pady=8)

        self.model_var = tk.StringVar()
        self.category_var = tk.StringVar()
        self.box_var = tk.StringVar()

        for col in (1, 4):
            lf.grid_columnconfigure(col, weight=1)

        r = 0
        ttk.Label(lf, text="Model*").grid(row=r, column=0, sticky="w", padx=6, pady=4)
        self.model_combo = ttk.Combobox(lf, textvariable=self.model_var, values=INVLISTS.get("models", []))
        self.model_combo.grid(row=r, column=1, sticky="we", padx=(0,6))
        ttk.Button(lf, text="Add Model", command=self.add_model_to_list)\
            .grid(row=r, column=2, sticky="w", padx=(0,12))

        ttk.Label(lf, text="Category*").grid(row=r, column=3, sticky="w", padx=6)
        self.category_combo = ttk.Combobox(lf, textvariable=self.category_var, values=INVLISTS.get("categories", []))
        self.category_combo.grid(row=r, column=4, sticky="we")
        ttk.Button(lf, text="Add Category", command=self.add_category_to_list)\
            .grid(row=r, column=5, sticky="w", padx=(6,0))

        r += 1
        ttk.Label(lf, text="Box #").grid(row=r, column=0, sticky="w", padx=6)
        self.box_combo = ttk.Combobox(lf, textvariable=self.box_var, values=INVLISTS.get("boxes", []))
        self.box_combo.grid(row=r, column=1, sticky="we", padx=(0,6))
        ttk.Button(lf, text="Add Box", command=self.add_box_to_list)\
            .grid(row=r, column=2, sticky="w", padx=(0,12))

        r += 1
        ttk.Label(lf, text="Serial Numbers* (comma-separated or one-per-line)").grid(row=r, column=0, columnspan=6, sticky="w", padx=6, pady=(6,2))
        r += 1
        self.serials_text_multi = tk.Text(lf, height=6)
        self.serials_text_multi.grid(row=r, column=0, columnspan=6, sticky="we", padx=6, pady=(0,6))

        r += 1
        ttk.Button(lf, text="Add to Inventory", command=self.add_items_bulk)\
            .grid(row=r, column=5, sticky="e", padx=6, pady=(0,6))

        # Table
        tbl = ttk.Frame(frm); tbl.pack(side="top", fill="both", expand=True, padx=8, pady=8)
        cols = ("id","Model","Category","Box #","Serial","Asset Tag #","Status/Custodian","Updated")
        self.tree = ttk.Treeview(tbl, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            self.tree.heading(c, text=c); self.tree.column(c, width=140, anchor="w")
        self.tree.column("id", width=50, anchor="center")
        self.tree.column("Status/Custodian", width=240)
        vsb = ttk.Scrollbar(tbl, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True); vsb.pack(side="right", fill="y")

        # Bottom bar: buttons (left) + counts (right)
        bottom = ttk.Frame(frm); bottom.pack(side="bottom", fill="x", padx=8, pady=8)
        btns = ttk.Frame(bottom); btns.pack(side="left")
        ttk.Button(btns, text="Delete Selected (to Recycle Bin)", command=self.delete_selected_to_recycle).pack(side="left", padx=4)
        ttk.Button(btns, text="Export CSV", command=self.export_csv).pack(side="left", padx=4)
        ttk.Button(btns, text="Import CSV", command=self.import_csv).pack(side="left", padx=4)
        ttk.Button(btns, text="Refresh", command=self._refresh_all_inventory_views).pack(side="left", padx=4)

        counts = ttk.Frame(bottom); counts.pack(side="right")
        self.lbl_onhand = ttk.Label(counts, text="On Hand: 0")
        self.lbl_issued = ttk.Label(counts, text="Currently Issued: 0")
        self.lbl_onhand.pack(anchor="e")
        self.lbl_issued.pack(anchor="e")

    # add-to-list helpers
    def add_model_to_list(self):
        val = self.model_var.get().strip()
        if not val:
            messagebox.showwarning("No value", "Enter a Model to add."); return
        INVLISTS["models"] = sorted(set(INVLISTS.get("models", []) + [val]))
        save_inventory_lists(INVLISTS)
        self.model_combo["values"] = INVLISTS["models"]
        messagebox.showinfo("Saved", f"Added to Model list:\n{val}")

    def add_box_to_list(self):
        val = self.box_var.get().strip()
        if not val:
            messagebox.showwarning("No value", "Enter a Box # to add."); return
        INVLISTS["boxes"] = sorted(set(INVLISTS.get("boxes", []) + [val]))
        save_inventory_lists(INVLISTS)
        self.box_combo["values"] = INVLISTS["boxes"]
        messagebox.showinfo("Saved", f"Added to Box list:\n{val}")

    def add_category_to_list(self):
        val = self.category_var.get().strip()
        if not val:
            messagebox.showwarning("No value", "Enter a Category to add."); return
        INVLISTS["categories"] = sorted(set(INVLISTS.get("categories", []) + [val]))
        save_inventory_lists(INVLISTS)
        self.category_combo["values"] = INVLISTS["categories"]
        messagebox.showinfo("Saved", f"Added to Category list:\n{val}")

    # add many serials at once
    def add_items_bulk(self):
        model = self.model_var.get().strip()
        category = self.category_var.get().strip()
        box = self.box_var.get().strip()
        if not model or not category:
            messagebox.showwarning("Missing", "Model and Category are required.")
            return

        serials = sanitize_serials_blob(self.serials_text_multi.get("1.0", "end"))
        if not serials:
            messagebox.showwarning("No Serials", "Paste or scan at least one serial number.")
            return

        added, dupes = 0, []
        for s in serials:
            try:
                db_add_item(model, category, box, s, None)
                added += 1
            except sqlite3.IntegrityError:
                dupes.append(s)

        # persist choices into dropdown lists
        changed = False
        if model and model not in INVLISTS["models"]:
            INVLISTS["models"].append(model); changed = True
        if box and box not in INVLISTS["boxes"]:
            INVLISTS["boxes"].append(box); changed = True
        if category and category not in INVLISTS["categories"]:
            INVLISTS["categories"].append(category); changed = True
        if changed:
            save_inventory_lists(INVLISTS)
            self.model_combo["values"] = sorted(set(INVLISTS["models"]))
            self.box_combo["values"]   = sorted(set(INVLISTS["boxes"]))
            self.category_combo["values"] = sorted(set(INVLISTS["categories"]))

        self.refresh_inventory()
        self.update_counts_labels()
        self.serials_text_multi.delete("1.0","end")
        msg = [f"Added {added} item(s) to inventory."]
        if dupes:
            msg.append(f"Skipped {len(dupes)} duplicate serial(s): {', '.join(dupes[:10])}" + ("..." if len(dupes)>10 else ""))
        messagebox.showinfo("Add to Inventory", "\n".join(msg))

    def delete_selected_to_recycle(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No selection", "Select one or more rows to delete.")
            return

        serials = []
        for iid in sel:
            vals = self.tree.item(iid, "values")
            serials.append(vals[4])

        # Look up status for all selected
        statuses = db_get_status_by_serials(serials)
        not_onhand = [s for s in serials if statuses.get(s, {}).get("status") != STATUS_ON_HAND]

        if not_onhand:
            details = []
            for s in not_onhand:
                st = statuses.get(s, {}).get("status", "Unknown")
                cust = statuses.get(s, {}).get("custodian", "")
                if st == STATUS_ISSUED and cust:
                    details.append(f"{s} (Issued to {cust})")
                else:
                    details.append(f"{s} (Status: {st})")
            messagebox.showerror(
                "Cannot Delete Issued Items",
                "You can only delete items that are On Hand.\n\n"
                "These serials are not On Hand and will be skipped:\n  " + "\n  ".join(details)
            )

        onhand_serials = [s for s in serials if s not in not_onhand]
        if not onhand_serials:
            return

        if not messagebox.askyesno("Confirm Deletion",
                                   f"Move {len(onhand_serials)} On-Hand item(s) to the Recycle Bin?"):
            return

        reason = simpledialog.askstring("Delete Reason (optional)", "Reason for deletion (optional):", parent=self)
        moved, skipped = db_soft_delete_onhand_by_serials(onhand_serials, reason)

        self.refresh_inventory()
        self.refresh_recycle()
        self.update_counts_labels()

        msg = [f"Moved {moved} item(s) to the Recycle Bin."]
        if skipped:
            msg.append(f"Skipped {len(skipped)} item(s) (not On Hand).")
        messagebox.showinfo("Deleted", "\n".join(msg))

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV","*.csv")],
                                            title="Export Inventory to CSV")
        if not path: return
        db_export_csv(path)
        messagebox.showinfo("Exported", f"Inventory exported to:\n{path}")

    def import_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV","*.csv")], title="Import Inventory from CSV")
        if not path: return
        try:
            added = db_import_csv(path)
            self.refresh_inventory()
            self.refresh_recycle()
            self.update_counts_labels()
            messagebox.showinfo("Imported", f"Imported {added} item(s).")
        except Exception as e:
            messagebox.showerror("Import Error", str(e))

    def _refresh_all_inventory_views(self):
        self.refresh_inventory()
        self.refresh_recycle()
        self.update_counts_labels()

    def refresh_inventory(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        for (id_, model, cat, box, serial, asset, status, cust, updated) in db_list_inventory():
            scell = status if status == STATUS_ON_HAND else f"{status} to {cust}"
            self.tree.insert("", "end", values=(id_, model, cat, box, serial, asset, scell, updated))

    def update_counts_labels(self):
        counts = db_counts_by_status()
        self.lbl_onhand.config(text=f"On Hand: {counts['on_hand']}")
        self.lbl_issued.config(text=f"Currently Issued: {counts['issued']}")

    # -- Issue tab
    def _build_issue_tab(self):
        frm = self.issue_frame
        lf = ttk.LabelFrame(frm, text="Issue Equipment"); lf.pack(side="top", fill="x", padx=8, pady=8)

        self.from_var = tk.StringVar()
        self.to_var = tk.StringVar()
        self.to_contact_var = tk.StringVar()

        r = 0
        ttk.Label(lf, text="From:").grid(row=r, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(lf, textvariable=self.from_var, width=40).grid(row=r, column=1, sticky="w")
        ttk.Label(lf, text="To (Person/Unit):").grid(row=r, column=2, sticky="w")
        ttk.Entry(lf, textvariable=self.to_var, width=40).grid(row=r, column=3, sticky="w")
        r += 1
        ttk.Label(lf, text="To (Contact Information):").grid(row=r, column=2, sticky="w")
        ttk.Entry(lf, textvariable=self.to_contact_var, width=40).grid(row=r, column=3, sticky="w")
        r += 1

        ttk.Label(lf, text="Scan/Enter Serials (comma-separated or one-per-line):").grid(row=r, column=0, columnspan=4, sticky="w", padx=6)
        r += 1
        self.serials_text_issue = tk.Text(lf, height=8)
        self.serials_text_issue.grid(row=r, column=0, columnspan=4, sticky="we", padx=6, pady=4)
        r += 1

        ttk.Button(lf, text="Validate On-Hand", command=self.validate_issue_serials).grid(row=r, column=0, sticky="w", padx=6, pady=4)
        ttk.Button(lf, text="Issue", command=self.issue_only).grid(row=r, column=1, sticky="w", padx=6)
        ttk.Button(lf, text="Clear Serials", command=lambda: self.serials_text_issue.delete("1.0","end")).grid(row=r, column=2, sticky="w", padx=6)

        lo = ttk.LabelFrame(frm, text="Validation Output")
        lo.pack(side="top", fill="both", expand=True, padx=8, pady=8)
        self.output_issue = tk.Text(lo, height=12); self.output_issue.pack(fill="both", expand=True)

    def append_issue_output(self, msg):
        self.output_issue.insert("end", msg + "\n"); self.output_issue.see("end")

    def validate_issue_serials(self):
        serials = sanitize_serials_blob(self.serials_text_issue.get("1.0","end"))
        if not serials:
            messagebox.showwarning("No Serials", "Please scan or enter serial numbers.")
            return
        onhand = db_find_onhand_by_serials(serials)
        found = {s for (_,_,_,_,s) in onhand}
        missing = [s for s in serials if s not in found]
        self.output_issue.delete("1.0","end")
        self.append_issue_output(f"Requested serials: {len(serials)}")
        self.append_issue_output(f"On-hand & available: {len(onhand)}")
        if missing:
            self.append_issue_output(f"Not available / not found ({len(missing)}): {', '.join(missing)}")
        else:
            self.append_issue_output("All requested serials are available.")

    def issue_only(self):
        issued_from = self.from_var.get().strip()
        issued_to   = self.to_var.get().strip()
        to_contact  = self.to_contact_var.get().strip()
        if not issued_from or not issued_to:
            messagebox.showwarning("Missing", "Please provide both 'From' and 'To (Person/Unit)'.")
            return
        serials = sanitize_serials_blob(self.serials_text_issue.get("1.0","end"))
        if not serials:
            messagebox.showwarning("No Serials", "Please scan or enter serial numbers.")
            return
        onhand = db_find_onhand_by_serials(serials)
        found = {s for (_id, _m, _c, _a, s) in onhand}
        missing = [s for s in serials if s not in found]
        if missing:
            messagebox.showerror("Cannot Issue", "Not on hand / not found:\n" + ", ".join(missing))
            return
        items = [{"model": m, "category": c, "serial": s, "asset_tag": a}
                 for (_id, m, c, a, s) in onhand]
        db_upsert_custodian_meta(issued_to, to_contact, issued_from)
        db_mark_issued(items, issued_from, issued_to)
        self.refresh_inventory()
        self.update_counts_labels()
        self.refresh_issued_lists()
        messagebox.showinfo("Issued", f"Issued {len(items)} item(s) to {issued_to}.\n"
                                      f"You can generate a 2062 later from the 'Issued Items' tab.")
        self.serials_text_issue.delete("1.0","end"); self.output_issue.delete("1.0","end")

    # -- Return tab
    def _build_return_tab(self):
        frm = self.return_frame
        lr = ttk.LabelFrame(frm, text="Return Equipment"); lr.pack(side="top", fill="x", padx=8, pady=8)
        ttk.Label(lr, text="Scan/Enter Serials to Return (newline or comma separated):").grid(row=0, column=0, columnspan=3, sticky="w", padx=6)
        self.return_text = tk.Text(lr, height=8); self.return_text.grid(row=1, column=0, columnspan=3, sticky="we", padx=6, pady=4)
        ttk.Button(lr, text="Validate Issued", command=self.validate_return_serials).grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Button(lr, text="Mark Returned", command=self.mark_returned).grid(row=2, column=1, sticky="w", padx=6, pady=4)
        ttk.Button(lr, text="Clear", command=lambda: self.return_text.delete("1.0","end")).grid(row=2, column=2, sticky="w", padx=6, pady=4)

        lo = ttk.LabelFrame(frm, text="Validation Output")
        lo.pack(side="top", fill="both", expand=True, padx=8, pady=8)
        self.output_return = tk.Text(lo, height=12); self.output_return.pack(fill="both", expand=True)

    def append_return_output(self, msg):
        self.output_return.insert("end", msg + "\n"); self.output_return.see("end")

    def validate_return_serials(self):
        serials = sanitize_serials_blob(self.return_text.get("1.0", "end"))
        if not serials:
            messagebox.showwarning("No Serials", "Please scan or enter serial numbers to validate.")
            return
        issued = db_find_issued_by_serials(serials)
        issued_found = {s for (_, _, _, _, s, _) in issued}
        missing = [s for s in serials if s not in issued_found]
        self.output_return.delete("1.0", "end")
        self.append_return_output(f"Entered serials: {len(serials)}")
        self.append_return_output(f"Currently issued: {len(issued)}")
        if issued:
            details = [f"{s} (to {cust})" for (_, _, _, _, s, cust) in issued]
            self.append_return_output("Details:\n  " + "\n  ".join(details))
        if missing:
            self.append_return_output(f"Not currently issued / not found ({len(missing)}): {', '.join(missing)}")

    def mark_returned(self):
        serials = sanitize_serials_blob(self.return_text.get("1.0","end"))
        if not serials:
            messagebox.showwarning("No Serials", "Please scan or enter serial numbers to return."); return
        updated = db_mark_returned(serials)
        self.refresh_inventory(); self.update_counts_labels(); self.refresh_issued_lists()
        messagebox.showinfo("Returned", f"Marked {updated} item(s) as returned (On Hand).")
        self.return_text.delete("1.0","end"); self.output_return.delete("1.0","end")

    # -- Issued Items tab
    def _build_issued_tab(self):
        frm = self.issued_frame
        top = ttk.Frame(frm); top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Filter custodians:").pack(side="left")
        self.filter_custodian_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.filter_custodian_var, width=30).pack(side="left", padx=6)
        ttk.Button(top, text="Apply", command=self.refresh_custodian_list).pack(side="left")
        ttk.Button(top, text="Clear", command=lambda: (self.filter_custodian_var.set(""), self.refresh_custodian_list())).pack(side="left", padx=4)

        body = ttk.Frame(frm); body.pack(fill="both", expand=True, padx=8, pady=8)

        left = ttk.Frame(body); left.pack(side="left", fill="y", padx=(0,8))
        ttk.Label(left, text="Custodians (To:)").pack(anchor="w")
        self.cust_list = ttk.Treeview(
            left,
            columns=("Custodian","Count","#IssuedBy","#Contact"),
            show="headings",
            height=22,
            selectmode="browse"
        )
        self.cust_list.heading("Custodian", text="Custodian")
        self.cust_list.heading("Count", text="# Items")
        self.cust_list.heading("#IssuedBy", text="Issued by")
        self.cust_list.heading("#Contact", text="Contact")

        self.cust_list.column("Custodian", width=240, anchor="w")
        self.cust_list.column("Count", width=70, anchor="center")
        self.cust_list.column("#IssuedBy", width=200, anchor="w")
        self.cust_list.column("#Contact", width=220, anchor="w")

        vsb_l = ttk.Scrollbar(left, orient="vertical", command=self.cust_list.yview)
        self.cust_list.configure(yscrollcommand=vsb_l.set)
        self.cust_list.pack(side="left", fill="y"); vsb_l.pack(side="left", fill="y", padx=(0,6))
        self.cust_list.bind("<<TreeviewSelect>>", lambda e: self.show_items_for_selected_custodian())

        edit_bar = ttk.Frame(left); edit_bar.pack(fill="x", pady=(6,0))
        ttk.Button(edit_bar, text="Edit Selected Metadata", command=self.edit_selected_custodian_meta).pack(side="left")

        right = ttk.Frame(body); right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="Items issued to selected custodian").pack(anchor="w")
        cols = ("Model","Category","Asset Tag #","Serial","Updated")
        self.cust_items = ttk.Treeview(right, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            self.cust_items.heading(c, text=c)
            self.cust_items.column(c, width=150 if c!="Updated" else 170, anchor="w")
        vsb_r = ttk.Scrollbar(right, orient="vertical", command=self.cust_items.yview)
        self.cust_items.configure(yscrollcommand=vsb_r.set)
        self.cust_items.pack(side="top", fill="both", expand=True); vsb_r.pack(side="right", fill="y")

        bottom = ttk.Frame(frm); bottom.pack(fill="x", padx=8, pady=6)
        ttk.Button(bottom, text="Refresh", command=self.refresh_issued_lists).pack(side="left")
        ttk.Button(bottom, text="Generate 2062 (Selected Custodian)", command=self.generate_2062_for_selected).pack(side="left", padx=8)

    def edit_selected_custodian_meta(self):
        sel = self.cust_list.selection()
        if not sel:
            messagebox.showwarning("No selection", "Select a custodian row first."); return
        custodian, *_ = self.cust_list.item(sel[0], "values")
        if str(custodian).strip() == "(Unassigned)":
            messagebox.showwarning("Unavailable", "Cannot edit metadata for (Unassigned)."); return
        current = db_get_custodian_meta(str(custodian))
        new_from = simpledialog.askstring("Edit Issued by (From)", "Issued by:", initialvalue=current.get("issued_from",""), parent=self)
        if new_from is None: return
        new_contact = simpledialog.askstring("Edit Contact", "Contact info:", initialvalue=current.get("contact",""), parent=self)
        if new_contact is None: return
        db_upsert_custodian_meta(str(custodian), new_contact, new_from)
        self.refresh_custodian_list()
        messagebox.showinfo("Saved", "Metadata updated.")

    def refresh_custodian_list(self):
        for i in self.cust_list.get_children(): self.cust_list.delete(i)
        filt = self.filter_custodian_var.get().strip().lower()
        rows = db_distinct_custodians_extended()
        for cust, cnt, issued_from, contact in rows:
            cust_disp = cust if cust else "(Unassigned)"
            if filt and filt not in cust_disp.lower(): continue
            self.cust_list.insert("", "end", values=(cust_disp, cnt, issued_from, contact))
        kids = self.cust_list.get_children()
        if kids and not self.cust_list.selection():
            self.cust_list.selection_set(kids[0])
        self.show_items_for_selected_custodian()

    def show_items_for_selected_custodian(self):
        for i in self.cust_items.get_children(): self.cust_items.delete(i)
        sel = self.cust_list.selection()
        if not sel:
            return
        custodian = self.cust_list.item(sel[0], "values")[0]
        if custodian == "(Unassigned)":
            return
        rows = db_list_issued_by_custodian(custodian)
        for (m, c, a, s, upd) in rows:
            self.cust_items.insert("", "end", values=(m, c, a, s, upd))

    def refresh_issued_lists(self):
        self.refresh_custodian_list()

    def generate_2062_for_selected(self):
        sel = self.cust_list.selection()
        if not sel:
            messagebox.showwarning("No selection", "Select a custodian in the list first."); return
        custodian = self.cust_list.item(sel[0], "values")[0]
        if custodian == "(Unassigned)":
            messagebox.showwarning("No custodian", "Please select a named custodian."); return
        items = db_list_issued_by_custodian(custodian)
        if not items:
            messagebox.showwarning("No items", f"No items currently issued to {custodian}."); return
        meta = db_get_custodian_meta(custodian)
        issued_from = meta.get("issued_from","") or simpledialog.askstring("From", "Enter FROM (issuing unit/person):", parent=self) or ""
        to_contact  = meta.get("contact","") or simpledialog.askstring("Contact Info", f"Enter contact info for {custodian} (optional):", parent=self) or ""
        db_upsert_custodian_meta(custodian, to_contact, issued_from)

        to_items = [{"model": m, "category": c, "asset_tag": a, "serial": s}
                    for (m, c, a, s, _upd) in items]
        rows = build_rows_grouped_by_model(to_items)

        to_name = sanitize_filename(custodian)[:60]
        default_name = f"DA2062_{to_name}_{datetime.now().strftime('%Y%m%d')}.pdf"
        path = filedialog.asksaveasfilename(defaultextension=".pdf",
                                            filetypes=[("PDF","*.pdf")],
                                            initialfile=default_name,
                                            title="Save DA Form 2062")
        if not path: return
        hdr = {"issued_from": issued_from, "issued_to": custodian, "to_contact": to_contact}
        try:
            render_2062_overlay(path, hdr, rows)
            messagebox.showinfo("Saved", f"DA Form 2062 saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("PDF Error", str(e))

    # -- Recycle Bin tab
    def _build_recycle_tab(self):
        frm = self.recycle_frame
        ttk.Label(frm, text="Items moved to Recycle Bin (soft-deleted from Inventory).").pack(anchor="w", padx=8, pady=(8,0))
        cont = ttk.Frame(frm); cont.pack(fill="both", expand=True, padx=8, pady=8)

        cols = ("id","Model","Category","Box #","Serial","Asset Tag #","Status/Custodian","Deleted Reason","Deleted At","Updated")
        self.recycle_tree = ttk.Treeview(cont, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            self.recycle_tree.heading(c, text=c)
            self.recycle_tree.column(c, width=140 if c not in ("Deleted Reason","Status/Custodian") else 220, anchor="w")
        self.recycle_tree.column("id", width=50, anchor="center")
        vsb = ttk.Scrollbar(cont, orient="vertical", command=self.recycle_tree.yview)
        self.recycle_tree.configure(yscrollcommand=vsb.set)
        self.recycle_tree.pack(side="left", fill="both", expand=True); vsb.pack(side="right", fill="y")

        btns = ttk.Frame(frm); btns.pack(fill="x", padx=8, pady=8)
        ttk.Button(btns, text="Restore Selected", command=self.restore_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="Permanently Delete Selected", command=self.purge_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="Refresh", command=self.refresh_recycle).pack(side="left", padx=4)

    def refresh_recycle(self):
        for i in self.recycle_tree.get_children(): self.recycle_tree.delete(i)
        for (id_, model, cat, box, serial, asset, status, cust, reason, deleted_at, updated) in db_list_recycle():
            scell = status if status == STATUS_ON_HAND else f"{status} to {cust}" if cust else status
            self.recycle_tree.insert("", "end", values=(id_, model, cat, box, serial, asset, scell, reason, deleted_at, updated))

    def restore_selected(self):
        sel = self.recycle_tree.selection()
        if not sel:
            messagebox.showwarning("No selection", "Select one or more rows to restore."); return
        serials = [self.recycle_tree.item(i, "values")[4] for i in sel]
        restored = db_restore_by_serials(serials)
        self.refresh_recycle()
        self.refresh_inventory()
        self.update_counts_labels()
        messagebox.showinfo("Restored", f"Restored {restored} item(s) back to Inventory.")

    def purge_selected(self):
        sel = self.recycle_tree.selection()
        if not sel:
            messagebox.showwarning("No selection", "Select one or more rows to permanently delete."); return
        count = len(sel)
        if not messagebox.askyesno("Permanently Delete", f"PERMANENTLY delete {count} item(s)? This cannot be undone."):
            return
        serials = [self.recycle_tree.item(i, "values")[4] for i in sel]
        deleted = db_purge_by_serials(serials)
        self.refresh_recycle()
        messagebox.showinfo("Deleted", f"Permanently deleted {deleted} item(s).")

    # -- Calibration tab with descriptions
    def _build_calibration_tab(self):
        frm = self.calib_frame
        info = ttk.LabelFrame(frm, text="How calibration works")
        info.pack(fill="x", padx=10, pady=8)
        ttk.Label(info, text=(
            "Lower Y values move text DOWN; higher Y values move text UP. X values move LEFT/RIGHT.\n"
            "Row height controls spacing between rows; Second line offset controls the small drop for the wrapped line inside a row."
        )).pack(anchor="w", padx=8, pady=6)

        grid = ttk.LabelFrame(frm, text="Overlay settings (points)")
        grid.pack(fill="both", expand=True, padx=10, pady=8)

        self.vars = {}
        fields = [
            ("item_desc_x", "Item description X (column C)", "Horizontal position for item description text."),
            ("qty_auth_x",  "QTY AUTH X (column G)", "Horizontal position for the quantity authorized."),
            ("item_start_y_first", "First page row-1 Y", "Baseline Y for the first row on page 1."),
            ("item_start_y_next",  "Next pages row-1 Y", "Baseline Y for the first row on pages 2+."),
            ("line_spacing", "Row height", "Vertical spacing between consecutive rows."),
            ("second_line_offset", "Second line offset (Y)", "How much the wrapped second line drops from the first line."),
            ("x_from",  "Header: FROM X", "Horizontal position of the FROM name (page 1 only)."),
            ("y_from",  "Header: FROM Y", "Vertical position of the FROM name (page 1 only)."),
            ("x_to",    "Header: TO X", "Horizontal position of the TO name (page 1 only)."),
            ("y_to",    "Header: TO Y", "Vertical position of the TO name (page 1 only)."),
            ("to_contact_offset", "TO contact offset", "Distance below TO for the contact info text."),
            ("y_identifier", "Page fraction baseline Y", "Vertical position of the page fraction (e.g., 1/3)."),
            ("x_page_right", "Page fraction right X", "Horizontal right-aligned position for the page fraction."),
            ("font_size", "Body font size", "Font size for item rows."),
            ("font_size_hdr", "Header font size", "Font size for header text."),
        ]
        # label | spinbox | description
        for i, (key, label, desc) in enumerate(fields):
            ttk.Label(grid, text=label).grid(row=i, column=0, sticky="w", padx=6, pady=4)
            init = getattr(LCFG, key)
            var = tk.DoubleVar(value=float(init)); self.vars[key] = var
            ttk.Spinbox(grid, textvariable=var, from_=0, to=1000, increment=0.5, width=10)\
                .grid(row=i, column=1, sticky="w", padx=6, pady=4)
            ttk.Label(grid, text=desc, foreground="#555").grid(row=i, column=2, sticky="w", padx=8, pady=4)

        ttk.Label(grid, text="Rows first page (logical rows)").grid(row=len(fields), column=0, sticky="w", padx=6, pady=4)
        self.vars["rows_first"] = tk.IntVar(value=int(LCFG.rows_first))
        ttk.Spinbox(grid, textvariable=self.vars["rows_first"], from_=1, to=30, increment=1, width=10)\
            .grid(row=len(fields), column=1, sticky="w", padx=6, pady=4)
        ttk.Label(grid, text="How many item rows page 1 can display.").grid(row=len(fields), column=2, sticky="w", padx=8, pady=4)

        ttk.Label(grid, text="Rows next pages (logical rows)").grid(row=len(fields)+1, column=0, sticky="w", padx=6, pady=4)
        self.vars["rows_next"] = tk.IntVar(value=int(LCFG.rows_next))
        ttk.Spinbox(grid, textvariable=self.vars["rows_next"], from_=1, to=30, increment=1, width=10)\
            .grid(row=len(fields)+1, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(grid, text="How many item rows pages 2+ can display.").grid(row=len(fields)+1, column=2, sticky="w", padx=8, pady=4)

        btns = ttk.Frame(frm); btns.pack(fill="x", padx=10, pady=8)
        ttk.Button(btns, text="Save", command=self.save_calibration).pack(side="left", padx=4)
        ttk.Button(btns, text="Reset Defaults", command=self.reset_calibration).pack(side="left", padx=4)

    def save_calibration(self):
        global LCFG
        for k, var in self.vars.items():
            val = var.get()
            try:
                if isinstance(getattr(LCFG, k), int):
                    setattr(LCFG, k, int(val))
                else:
                    setattr(LCFG, k, float(val))
            except Exception:
                setattr(LCFG, k, val)
        LCFG.rows_first = int(self.vars["rows_first"].get())
        LCFG.rows_next  = int(self.vars["rows_next"].get())
        save_layout(LCFG)
        messagebox.showinfo("Saved", f"Calibration saved to {LAYOUT_FILE}.")

    def reset_calibration(self):
        global LCFG
        LCFG = LayoutConfig(); save_layout(LCFG)
        for k, var in self.vars.items(): var.set(getattr(LCFG, k))
        messagebox.showinfo("Reset", "Calibration reset to defaults.")

# ---- main
if __name__ == "__main__":
    try:
        init_db(); migrate_db()
        app = App(); app.mainloop()
    except Exception:
        _startup_error_dialog(); raise