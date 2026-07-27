from __future__ import annotations

import sqlite3
from pathlib import Path

import assettrack.db as db
from assettrack.import_analysis import analyze_asset_import_csv
from assettrack.import_reconciliation import build_asset_import_preview
from tools.asset_import_scale_check import ScalePlan, build_upload_csv, run_scale_check, seed_database


def test_scale_dataset_has_required_categories_at_small_size(tmp_path: Path, monkeypatch) -> None:
    plan = ScalePlan(
        existing_assets=20,
        new_unique_rows=2,
        matching_rows=2,
        update_rows=2,
        identity_conflict_rows=1,
        duplicate_pairs=1,
        invalid_rows=1,
        slot_conflict_rows=1,
    )
    db_path = tmp_path / "assettrack.sqlite"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    conn = db.get_connection()
    try:
        seed_database(conn, plan)
    finally:
        conn.close()

    upload_path = tmp_path / "assets.csv"
    upload_path.write_bytes(build_upload_csv(plan))
    analysis = analyze_asset_import_csv(upload_path, filename="assets.csv", collect_row_errors=True)
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        preview = build_asset_import_preview(conn, analysis, unslotted_acknowledged=True)
    finally:
        conn.close()

    assert plan.upload_rows == 11
    assert preview.totals == plan.expected_category_totals
    assert preview.totals["new_asset"] > 0
    assert preview.totals["unchanged_exact_match"] > 0
    assert preview.totals["proposed_update"] > 0
    assert preview.totals["identity_conflict"] > 0
    assert preview.totals["invalid_duplicate_upload_row"] > 0
    assert preview.totals["slot_conflict_unslotted"] > 0


def test_scale_check_verifies_commit_integrity_and_rollback(tmp_path: Path) -> None:
    plan = ScalePlan(
        existing_assets=20,
        new_unique_rows=2,
        matching_rows=2,
        update_rows=2,
        identity_conflict_rows=1,
        duplicate_pairs=1,
        invalid_rows=1,
        slot_conflict_rows=1,
    )

    result = run_scale_check(plan, db_path=tmp_path / "assettrack.sqlite")

    assert result["dataset"]["upload_rows"] == 11
    assert result["category_totals"] == plan.expected_category_totals
    assert result["integrity"]["counts_match"] is True
    assert result["integrity"]["reconciliation_ok"] is True
    assert result["integrity"]["blocked_rows_inserted"] == 0
    assert result["integrity"]["busy_slots_changed"] == 0
    assert result["rollback"]["verified"] is True
