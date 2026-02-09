# ⚠️ Disclaimer (Not Government Endorsed)

This software is an independent tool and is **not affiliated with, endorsed by, or sponsored by** the U.S. Department of War (DoW), U.S. Department of Defense (DoD), or any other government agency. Use of this software does **not** imply compliance with or substitution for official DoW/DoD policies, forms, or procedures. **You are responsible** for verifying accuracy and complying with all applicable regulations and for using official systems where required.

---

# AssetTrack

AssetTrack is an offline-first asset intake and accountability system designed for environments where reliability matters more than polish.

It provides a disciplined workflow for scanning physical assets, reviewing staged intake data, and committing records atomically to a local SQLite database. The system is intentionally simple, portable, and auditable.

AssetTrack supports:
- Barcode scanning into a preview queue
- Operator review with explicit confirmation before commit
- Atomic writes to SQLite (no partial state)
- Offline operation with no external service dependencies
- Dockerized deployment with explicit data persistence

AssetTrack is optimized for field use, controlled networks, and operational settings where accidental data loss, silent failures, or hidden state are unacceptable.

---

## Current Capabilities (Authoritative)

The sections below are in the process of being revised.  
The list here reflects the **current, verified behavior** of AssetTrack.

AssetTrack currently provides:
- Offline-first operation with no external service dependencies
- Barcode scanning into a staged **preview queue**
- Preview validation prior to commit
- Explicit operator review confirmation before commit
- Atomic commits to a local SQLite database
- Deterministic clearing of the preview queue on successful commit
- Dockerized execution with explicit host-mounted data persistence

Capabilities related to PDF generation, DA Form 2062, GUI tabs, recycle bins, or calibration tools are **not part of the current AssetTrack system** and will be removed or archived as documentation cleanup continues.

---

## 📌 Features

- **Inventory Management**
  - Track **Model, Category, Box #, Serial** (Asset Tag stored in DB only).
  - Bulk add serials (comma-separated **or** one-per-line).
  - Managed dropdowns for **Model / Category / Box** stored in `inventory_lists.json`.
  - Import/Export CSV.

- **Issuing & Returning**
  - Separate **Issue** and **Return** tabs with validation.
  - Custodian metadata: **Issued by (From)** and **Contact** stored per custodian.

- **Issued Items Overview**
  - See all items currently issued by custodian.
  - Edit custodian’s **Issued by** and **Contact**.
  - Generate DA 2062 **on demand** for any custodian.

- **DA 2062 Generation**
  - Uses `DA2062_flat.pdf` as a template.
  - Auto-groups by model.
  - **10 serials per row** (first line: Model + 4 S/N, wrapped line: 6 S/N).
  - Automatic pagination with page indicator `1/N`, `2/N`, etc.
  - Calibration tab for fine-tuning overlay positions.

- **Recycle Bin**
  - Delete is **allowed only for On Hand** items.
  - Issued items cannot be deleted.
  - Restore or permanently purge deleted items.

---

## ⚙️ Requirements

- **Python**: 3.10+
- **Dependencies**:
  ```bash
  python -m pip install --upgrade pypdf reportlab pandas openpyxl cryptography
  ```
- **Template**: `DA2062_flat.pdf` (flattened version of DA Form 2062) placed in the same folder as the script.

---

## 🚀 Quick Start

1. Clone or download the repository.
2. Place `DA2062_flat.pdf` next to `hand_receipt_manager.py`.
3. Install dependencies:
   ```bash
   python -m pip install --upgrade pypdf reportlab pandas openpyxl cryptography
   ```
4. Run the app:
   ```bash
   python hand_receipt_manager.py
   ```

On first run, the following files are created:
- `inventory.db` — SQLite database
- `inventory_lists.json` — Model/Category/Box dropdown values
- `da2062_layout.json` — Calibration settings

---

## 📖 Application Guide

### Inventory Tab
- Add items by selecting **Model**, **Category**, and optional **Box #**.
- Paste/scan multiple serial numbers.
- Use **Add Model / Add Category / Add Box** to update dropdown lists.
- Delete moves On Hand items to the **Recycle Bin**.

### Issue Tab
- Fill out **From**, **To (Person/Unit)**, and **Contact**.
- Scan/enter serials, validate, then issue.
- Issued items are tracked under the custodian.

### Return Tab
- Scan/enter serials to validate and mark them returned.

### Issued Items Tab
- Shows custodians with their issued counts, **Issued by**, and **Contact**.
- Generate DA 2062 for the selected custodian.
- File name format:  
  ```
  DA2062_{Custodian}_{YYYYMMDD}.pdf
  ```

### Recycle Bin Tab
- Soft-deleted items are listed.
- Restore or permanently delete.
- Only **On Hand** items can be deleted.

### Calibration Tab
- Fine-tune X/Y positions and font sizes for overlay fields.
- Reset or save calibration settings.

---

## 📦 Import/Export

- **Export CSV**: Save current inventory (excludes deleted).
- **Import CSV**: Add/update items. Revives soft-deleted serials if matched.

CSV required columns:
- `Model`, `Category`, `Serial Number`  
Optional: `Box #`, `Asset Tag #`

---

## 🖨️ DA 2062 Generation

- Grouped by model.
- Each row can contain up to 10 serials:
  - Line 1: Model + 4 serials
  - Line 2: 6 more serials (wrapped)
- Page 2+ does not repeat To/From headers.
- Contact information is displayed below the To field.

---

## 🔒 Security & Privacy

- All data stays local in `inventory.db`.
- Exported CSVs and PDFs may contain sensitive equipment data—handle accordingly.

---

## 🛠️ Building an EXE (Optional)

You can bundle the app with **PyInstaller**:

```bash
python -m pip install pyinstaller
pyinstaller ^
  --onefile ^
  --name HandReceiptManager ^
  --add-data "DA2062_flat.pdf;." ^
  hand_receipt_manager.py
```

This creates `dist/HandReceiptManager.exe`.

---

## 📂 Files Created

- `inventory.db` — SQLite database
- `inventory_lists.json` — Dropdown values
- `da2062_layout.json` — Calibration settings
- `DA2062_flat.pdf` — Flattened DA Form 2062 template (required)

---

## 🧰 Troubleshooting

- **Missing modules** → Reinstall requirements:
  ```bash
  python -m pip install --upgrade pypdf reportlab pandas openpyxl cryptography
  ```
- **Template not found** → Ensure `DA2062_flat.pdf` is next to the script.
- **Encrypted template** → You’ll be prompted for a password.
- **Cannot delete issued items** → Only On Hand items can be deleted.

---
---

## 🖼️ Application Gallery

Below are example screenshots of the Hand Receipt Manager interface and generated DA Form 2062.

| Inventory Tab | Issue Tab | Return Tab |
|----------------|------------|-------------|
| ![Inventory Tab](images/inventory_tab.png) | ![Issue Tab](images/issue_tab.png) | ![Return Tab](images/return_tab.png) |

| Issued Items | Recycle Bin | Calibration |
|---------------|--------------|--------------|
| ![Issued Items Tab](images/issued_items_tab.png) | ![Recycle Bin Tab](images/recycle_bin_tab.png) | ![Calibration Tab](images/calibration_tab.png) |

| Generated 2062 Form |
|----------------------|
| ![Generated 2062](images/generated_2062.png) |

---

