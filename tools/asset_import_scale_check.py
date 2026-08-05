from __future__ import annotations

import argparse
import csv
import io
import json
import re
import resource
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assettrack.auth as auth
import assettrack.db as db
from assettrack.import_analysis import analyze_asset_import_csv
from assettrack.import_reconciliation import build_asset_import_preview
from assettrack.intake import app as intake_app


@dataclass(frozen=True)
class ScalePlan:
    existing_assets: int = 100_000
    new_unique_rows: int = 2_000
    matching_rows: int = 2_000
    update_rows: int = 2_000
    identity_conflict_rows: int = 1_000
    duplicate_pairs: int = 500
    invalid_rows: int = 1_000
    slot_conflict_rows: int = 1_000

    @property
    def upload_rows(self) -> int:
        return (
            self.new_unique_rows
            + self.matching_rows
            + self.update_rows
            + self.identity_conflict_rows
            + (self.duplicate_pairs * 2)
            + self.invalid_rows
            + self.slot_conflict_rows
        )

    @property
    def slotted_new_rows(self) -> int:
        return self.new_unique_rows + self.duplicate_pairs

    @property
    def committed_created_rows(self) -> int:
        return self.slotted_new_rows + self.slot_conflict_rows

    @property
    def committed_updated_rows(self) -> int:
        return self.update_rows

    @property
    def committed_rows(self) -> int:
        return self.committed_created_rows + self.committed_updated_rows

    @property
    def blocked_rows(self) -> int:
        return self.identity_conflict_rows + self.duplicate_pairs + self.invalid_rows

    @property
    def expected_category_totals(self) -> dict[str, int]:
        return {
            "new_asset": self.slotted_new_rows,
            "unchanged_exact_match": self.matching_rows,
            "proposed_update": self.update_rows,
            "unslotted_import": 0,
            "slot_conflict_unslotted": self.slot_conflict_rows,
            "blocked_conflict": 0,
            "identity_conflict": self.identity_conflict_rows,
            "invalid_duplicate_upload_row": self.duplicate_pairs + self.invalid_rows,
            "case_over_capacity": 0,
        }


def _now() -> str:
    return "2026-01-01T00:00:00+00:00"


def _maxrss_mb() -> float:
    maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(maxrss / divisor, 2)


def _validate_plan(plan: ScalePlan) -> None:
    required_existing = plan.matching_rows + plan.update_rows + plan.identity_conflict_rows + plan.slot_conflict_rows
    if plan.existing_assets < required_existing:
        raise ValueError(f"existing_assets must be at least {required_existing}.")
    if plan.upload_rows <= 0:
        raise ValueError("upload_rows must be positive.")


def _seed_slots(conn: sqlite3.Connection, plan: ScalePlan) -> None:
    slots: list[tuple[int, str, int, str | None]] = []
    next_slot_id = 1
    for position in range(1, plan.matching_rows + 1):
        slots.append((next_slot_id, "CASE-EXACT", position, f"EXIST-{position:06d}"))
        next_slot_id += 1
    for offset, position in enumerate(range(1, plan.update_rows + 1), start=plan.matching_rows + 1):
        slots.append((next_slot_id, "CASE-UPD", position, f"EXIST-{offset:06d}"))
        next_slot_id += 1
    conflict_start = plan.matching_rows + plan.update_rows + plan.identity_conflict_rows + 1
    for offset, position in enumerate(range(1, plan.slot_conflict_rows + 1), start=conflict_start):
        slots.append((next_slot_id, "CASE-BUSY", position, f"EXIST-{offset:06d}"))
        next_slot_id += 1
    for position in range(1, plan.slotted_new_rows + 1):
        slots.append((next_slot_id, "CASE-NEW", position, None))
        next_slot_id += 1
    conn.executemany(
        "INSERT INTO slots (id, case_name, slot_position, current_asset_tag) VALUES (?, ?, ?, ?);",
        slots,
    )


def _seed_assets(conn: sqlite3.Connection, plan: ScalePlan) -> None:
    occupied_slot_by_asset: dict[int, int] = {}
    next_slot_id = 1
    for asset_index in range(1, plan.matching_rows + 1):
        occupied_slot_by_asset[asset_index] = next_slot_id
        next_slot_id += 1
    for asset_index in range(plan.matching_rows + 1, plan.matching_rows + plan.update_rows + 1):
        occupied_slot_by_asset[asset_index] = next_slot_id
        next_slot_id += 1
    conflict_start = plan.matching_rows + plan.update_rows + plan.identity_conflict_rows + 1
    for asset_index in range(conflict_start, conflict_start + plan.slot_conflict_rows):
        occupied_slot_by_asset[asset_index] = next_slot_id
        next_slot_id += 1

    assets = []
    for asset_index in range(1, plan.existing_assets + 1):
        home_slot_id = occupied_slot_by_asset.get(asset_index)
        case_number = ""
        slot_number = ""
        if home_slot_id is not None:
            if asset_index <= plan.matching_rows:
                case_number = "CASE-EXACT"
                slot_number = str(asset_index)
            elif asset_index <= plan.matching_rows + plan.update_rows:
                case_number = "CASE-UPD"
                slot_number = str(asset_index - plan.matching_rows)
            else:
                case_number = "CASE-BUSY"
                slot_number = str(asset_index - conflict_start + 1)
        assets.append(
            (
                f"EXIST-{asset_index:06d}",
                f"SER-EXIST-{asset_index:06d}",
                ["laptop", "switch", "router"][asset_index % 3],
                "Baseline Maker",
                "Baseline Model",
                "in_stock",
                "accountable",
                "serviceable",
                _now(),
                "STORAGE",
                home_slot_id,
                case_number,
                slot_number,
            )
        )
    conn.executemany(
        """
        INSERT INTO assets (
            asset_tag, serial_number, equipment_type, manufacturer, model, custody_state,
            accountability_status, condition, created_date, location_type, home_slot_id,
            case_number, slot_number
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        assets,
    )
    occupancy = [
        (slot_id, asset_index, _now())
        for asset_index, slot_id in sorted(occupied_slot_by_asset.items())
    ]
    conn.executemany(
        "INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at) VALUES (?, ?, ?);",
        occupancy,
    )


def seed_database(conn: sqlite3.Connection, plan: ScalePlan) -> None:
    _validate_plan(plan)
    _seed_slots(conn, plan)
    _seed_assets(conn, plan)
    conn.commit()


def build_upload_csv(plan: ScalePlan) -> bytes:
    _validate_plan(plan)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["asset_tag", "serial_number", "equipment_type", "manufacturer", "model", "case_identifier", "slot_identifier"])

    new_slot_position = 1
    for index in range(1, plan.new_unique_rows + 1):
        writer.writerow(
            [
                f"NEW-{index:06d}",
                f"SER-NEW-{index:06d}",
                "laptop",
                "Dell",
                "Latitude",
                "CASE-NEW",
                new_slot_position,
            ]
        )
        new_slot_position += 1

    for index in range(1, plan.matching_rows + 1):
        writer.writerow(
            [
                f"EXIST-{index:06d}",
                f"SER-EXIST-{index:06d}",
                ["laptop", "switch", "router"][index % 3],
                "Baseline Maker",
                "Baseline Model",
                "CASE-EXACT",
                index,
            ]
        )

    update_start = plan.matching_rows + 1
    for offset, asset_index in enumerate(range(update_start, update_start + plan.update_rows), start=1):
        writer.writerow(
            [
                f"EXIST-{asset_index:06d}",
                f"SER-EXIST-{asset_index:06d}",
                ["laptop", "switch", "router"][asset_index % 3],
                "Updated Maker",
                "Updated Model",
                "CASE-UPD",
                offset,
            ]
        )

    conflict_serial_start = plan.matching_rows + plan.update_rows + 1
    for offset, asset_index in enumerate(range(conflict_serial_start, conflict_serial_start + plan.identity_conflict_rows), start=1):
        writer.writerow(
            [
                f"CONFLICT-{offset:06d}",
                f"SER-EXIST-{asset_index:06d}",
                "router",
                "Juniper",
                "MX",
                "",
                "",
            ]
        )

    for index in range(1, plan.duplicate_pairs + 1):
        asset_tag = f"DUP-{index:06d}"
        for duplicate_index in range(2):
            writer.writerow(
                [
                    asset_tag,
                    f"SER-DUP-{index:06d}-{duplicate_index}",
                    "switch",
                    "Cisco",
                    "Catalyst",
                    "CASE-NEW",
                    new_slot_position,
                ]
            )
        new_slot_position += 1

    for index in range(1, plan.invalid_rows + 1):
        writer.writerow(["", f"SER-INVALID-{index:06d}", "laptop", "Dell", "Latitude", "", ""])

    for index in range(1, plan.slot_conflict_rows + 1):
        writer.writerow(
            [
                f"BUSY-NEW-{index:06d}",
                f"SER-BUSY-NEW-{index:06d}",
                "switch",
                "Cisco",
                "Catalyst",
                "CASE-BUSY",
                index,
            ]
        )

    return output.getvalue().encode("utf-8")


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "assets": int(conn.execute("SELECT COUNT(*) FROM assets;").fetchone()[0]),
        "asset_events": int(conn.execute("SELECT COUNT(*) FROM asset_events;").fetchone()[0]),
        "slot_occupancy": int(conn.execute("SELECT COUNT(*) FROM slot_occupancy;").fetchone()[0]),
    }


def _reconciliation_mismatches(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "asset_home_without_matching_occupancy": int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM assets a
                LEFT JOIN slot_occupancy so
                  ON so.asset_id = a.id AND so.slot_id = a.home_slot_id
                WHERE a.home_slot_id IS NOT NULL
                  AND so.id IS NULL;
                """
            ).fetchone()[0]
        ),
        "occupancy_without_matching_asset_home": int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM slot_occupancy so
                JOIN assets a ON a.id = so.asset_id
                WHERE a.home_slot_id IS NULL
                   OR a.home_slot_id != so.slot_id;
                """
            ).fetchone()[0]
        ),
        "slot_current_tag_mismatch": int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM slot_occupancy so
                JOIN slots s ON s.id = so.slot_id
                JOIN assets a ON a.id = so.asset_id
                WHERE COALESCE(s.current_asset_tag, '') != a.asset_tag;
                """
            ).fetchone()[0]
        ),
    }


def _login_admin(client) -> None:
    now_iso = _now()
    conn = sqlite3.connect(db.DB_PATH)
    try:
        cursor = conn.execute(
            """
            INSERT INTO users (username, password_hash, role, active, created_at, updated_at)
            VALUES (?, ?, 'admin', 1, ?, ?);
            """,
            ("scale-admin", "assettrack-scale-check", now_iso, now_iso),
        )
        conn.commit()
        admin_id = int(cursor.lastrowid)
    finally:
        conn.close()
    current_time = auth.now_seconds()
    with client.session_transaction() as sess:
        sess["user_id"] = admin_id
        sess["last_seen"] = current_time
        sess["session_started_at"] = current_time


def _preview_token(response_data: bytes) -> str:
    match = re.search(rb'name="preview_token" value="([a-f0-9]{64})"', response_data)
    if match is None:
        raise RuntimeError("preview token was not rendered")
    return match.group(1).decode("ascii")


def _run_commit(client, token: str):
    return client.post(
        "/admin/assets/import",
        data={"action": "commit", "preview_token": token, "confirm_import": "1"},
    )


def verify_atomic_rollback(client) -> dict[str, object]:
    conn = db.get_connection()
    try:
        next_slot_id = int(conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM slots;").fetchone()[0])
        conn.execute("INSERT INTO slots (id, case_name, slot_position, current_asset_tag) VALUES (?, ?, ?, NULL);", (next_slot_id, "CASE-ROLLBACK", 1))
        conn.execute("INSERT INTO slots (id, case_name, slot_position, current_asset_tag) VALUES (?, ?, ?, NULL);", (next_slot_id + 1, "CASE-ROLLBACK", 2))
        conn.commit()
        before = _counts(conn)
    finally:
        conn.close()

    csv_content = (
        b"asset_tag,serial_number,equipment_type,manufacturer,model,case_identifier,slot_identifier\n"
        b"ROLLBACK-A,SER-ROLLBACK-A,laptop,Dell,Latitude,CASE-ROLLBACK,1\n"
        b"ROLLBACK-B,SER-ROLLBACK-B,laptop,Dell,Latitude,CASE-ROLLBACK,2\n"
    )
    response = client.post(
        "/admin/assets/import",
        data={"acknowledge_unslotted": "1", "asset_file": (io.BytesIO(csv_content), "rollback.csv")},
        content_type="multipart/form-data",
    )
    if response.status_code != 200:
        raise RuntimeError(f"rollback preview failed with HTTP {response.status_code}")
    token = _preview_token(response.data)

    original_create = intake_app._asset_import_create_new_asset

    def failing_create(*args, **kwargs):
        row = args[1] if len(args) > 1 else kwargs.get("row")
        result = original_create(*args, **kwargs)
        if getattr(row, "asset_tag", "") == "ROLLBACK-A":
            raise ValueError("scale rollback probe")
        return result

    intake_app._asset_import_create_new_asset = failing_create
    try:
        commit_response = _run_commit(client, token)
    finally:
        intake_app._asset_import_create_new_asset = original_create

    conn = db.get_connection()
    try:
        after = _counts(conn)
        inserted = int(
            conn.execute(
                "SELECT COUNT(*) FROM assets WHERE asset_tag IN ('ROLLBACK-A', 'ROLLBACK-B');"
            ).fetchone()[0]
        )
    finally:
        conn.close()
    return {
        "verified": commit_response.status_code == 200 and b"scale rollback probe" in commit_response.data and before == after and inserted == 0,
        "before_counts": before,
        "after_counts": after,
        "inserted_probe_assets": inserted,
    }


def run_scale_check(plan: ScalePlan, *, db_path: Path, progress: Callable[[str], None] | None = None) -> dict[str, object]:
    progress = progress or (lambda _message: None)
    _validate_plan(plan)
    db.DB_PATH = db_path
    previous_testing = intake_app.app.config.get("TESTING")
    previous_propagate_exceptions = intake_app.app.config.get("PROPAGATE_EXCEPTIONS")
    intake_app.app.config["TESTING"] = True
    intake_app.app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        return _run_scale_check(plan, db_path=db_path, progress=progress)
    finally:
        intake_app.app.config["TESTING"] = previous_testing
        intake_app.app.config["PROPAGATE_EXCEPTIONS"] = previous_propagate_exceptions


def _run_scale_check(plan: ScalePlan, *, db_path: Path, progress: Callable[[str], None]) -> dict[str, object]:
    progress(f"initializing database at {db_path}")
    conn = db.get_connection()
    try:
        seed_start = perf_counter()
        seed_database(conn, plan)
        seed_seconds = perf_counter() - seed_start
        before_counts = _counts(conn)
    finally:
        conn.close()

    upload_content = build_upload_csv(plan)
    upload_path = db_path.parent / "asset_import_scale_upload.csv"
    upload_path.write_bytes(upload_content)

    memory_before_mb = _maxrss_mb()
    progress("measuring analysis")
    analysis_start = perf_counter()
    analysis = analyze_asset_import_csv(upload_path, filename=upload_path.name, collect_row_errors=True)
    analysis_seconds = perf_counter() - analysis_start

    progress("measuring preview")
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        preview_start = perf_counter()
        preview = build_asset_import_preview(conn, analysis, unslotted_acknowledged=True)
        preview_seconds = perf_counter() - preview_start
        progress(f"preview measured in {preview_seconds:.3f}s")
        category_totals = preview.totals
    finally:
        conn.close()

    if category_totals != plan.expected_category_totals:
        raise RuntimeError(f"unexpected category totals: {category_totals}")
    progress("category totals verified")

    client = intake_app.app.test_client()
    _login_admin(client)

    progress("preparing pending preview through upload route")
    route_preview_start = perf_counter()
    response = client.post(
        "/admin/assets/import",
        data={"acknowledge_unslotted": "1", "asset_file": (io.BytesIO(upload_content), upload_path.name)},
        content_type="multipart/form-data",
    )
    route_preview_seconds = perf_counter() - route_preview_start
    if response.status_code != 200:
        raise RuntimeError(f"upload route failed with HTTP {response.status_code}")
    token = _preview_token(response.data)

    progress("measuring commit")
    commit_start = perf_counter()
    commit_response = _run_commit(client, token)
    commit_seconds = perf_counter() - commit_start
    if commit_response.status_code != 200 or b"Asset import committed." not in commit_response.data:
        raise RuntimeError(f"commit failed with HTTP {commit_response.status_code}")

    progress("checking integrity")
    conn = db.get_connection()
    try:
        after_counts = _counts(conn)
        mismatches = _reconciliation_mismatches(conn)
        blocked_inserted = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM assets
                WHERE asset_tag LIKE 'CONFLICT-%'
                   OR asset_tag LIKE 'SER-INVALID-%';
                """
            ).fetchone()[0]
        )
        busy_slot_changed = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM slots
                WHERE case_name = 'CASE-BUSY'
                  AND current_asset_tag NOT LIKE 'EXIST-%';
                """
            ).fetchone()[0]
        )
    finally:
        conn.close()

    expected_after_counts = {
        "assets": before_counts["assets"] + plan.committed_created_rows,
        "asset_events": before_counts["asset_events"] + (plan.slotted_new_rows * 2) + plan.slot_conflict_rows + plan.update_rows,
        "slot_occupancy": before_counts["slot_occupancy"] + plan.slotted_new_rows,
    }
    integrity = {
        "expected_after_counts": expected_after_counts,
        "actual_after_counts": after_counts,
        "counts_match": after_counts == expected_after_counts,
        "reconciliation_mismatches": mismatches,
        "reconciliation_ok": all(value == 0 for value in mismatches.values()),
        "blocked_rows_inserted": blocked_inserted,
        "busy_slots_changed": busy_slot_changed,
    }
    if not integrity["counts_match"] or not integrity["reconciliation_ok"] or blocked_inserted or busy_slot_changed:
        raise RuntimeError(f"integrity check failed: {integrity}")

    progress("checking rollback")
    rollback = verify_atomic_rollback(client)
    if not rollback["verified"]:
        raise RuntimeError(f"rollback check failed: {rollback}")

    return {
        "dataset": {
            "existing_assets": plan.existing_assets,
            "upload_rows": plan.upload_rows,
            "new_unique_rows": plan.new_unique_rows,
            "matching_rows": plan.matching_rows,
            "update_rows": plan.update_rows,
            "identity_conflict_rows": plan.identity_conflict_rows,
            "duplicate_pairs": plan.duplicate_pairs,
            "invalid_rows": plan.invalid_rows,
            "slot_conflict_rows": plan.slot_conflict_rows,
        },
        "durations_seconds": {
            "seed": round(seed_seconds, 3),
            "analysis": round(analysis_seconds, 3),
            "preview": round(preview_seconds, 3),
            "route_preview": round(route_preview_seconds, 3),
            "commit": round(commit_seconds, 3),
        },
        "category_totals": category_totals,
        "memory": {
            "maxrss_before_mb": memory_before_mb,
            "maxrss_after_mb": _maxrss_mb(),
        },
        "integrity": integrity,
        "rollback": rollback,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Asset Import scale and integrity check.")
    parser.add_argument("--existing-assets", type=int, default=100_000)
    parser.add_argument("--new-unique-rows", type=int, default=2_000)
    parser.add_argument("--matching-rows", type=int, default=2_000)
    parser.add_argument("--update-rows", type=int, default=2_000)
    parser.add_argument("--identity-conflict-rows", type=int, default=1_000)
    parser.add_argument("--duplicate-pairs", type=int, default=500)
    parser.add_argument("--invalid-rows", type=int, default=1_000)
    parser.add_argument("--slot-conflict-rows", type=int, default=1_000)
    parser.add_argument("--db-path", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    plan = ScalePlan(
        existing_assets=args.existing_assets,
        new_unique_rows=args.new_unique_rows,
        matching_rows=args.matching_rows,
        update_rows=args.update_rows,
        identity_conflict_rows=args.identity_conflict_rows,
        duplicate_pairs=args.duplicate_pairs,
        invalid_rows=args.invalid_rows,
        slot_conflict_rows=args.slot_conflict_rows,
    )
    def progress(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    if args.db_path is not None:
        result = run_scale_check(plan, db_path=args.db_path, progress=progress)
    else:
        with tempfile.TemporaryDirectory(prefix="asset-import-scale-") as temp_dir:
            result = run_scale_check(plan, db_path=Path(temp_dir) / "assettrack-scale.sqlite", progress=progress)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
