from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import assettrack.db as db
from assettrack.custody_accountability import build_custody_accountability_report
from assettrack.custody_analytics import (
    build_analytics_dataset,
)


GENERATED_AT = datetime(2026, 1, 20, 12, 0, tzinfo=timezone.utc)


class CustodyAnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "assettrack.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        db._create_schema(self.conn)
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def _snapshot(self) -> dict[str, tuple[tuple[object, ...], ...]]:
        snapshot: dict[str, tuple[tuple[object, ...], ...]] = {}
        for table in ("assets", "asset_events", "holders", "slots"):
            rows = self.conn.execute(f"SELECT * FROM {table} ORDER BY rowid;").fetchall()
            snapshot[table] = tuple(tuple(row) for row in rows)
        return snapshot

    def _insert_holder(self, holder_id: int, name: str, organization: str) -> None:
        self.conn.execute(
            """
            INSERT INTO holders (
                id, holder_type, name, organization, identifier, email, contact_info, created_at, updated_at
            )
            VALUES (?, 'PERSON', ?, ?, ?, '', NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """,
            (holder_id, name, organization, f"H-{holder_id}"),
        )
        self.conn.commit()

    def _insert_asset(
        self,
        asset_tag: str,
        *,
        equipment_type: str = "laptop",
        location_type: str = "STORAGE",
        current_holder_id: int | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO assets (
                asset_tag, serial_number, equipment_type, location_type, current_holder_id
            )
            VALUES (?, ?, ?, ?, ?);
            """,
            (asset_tag, f"SER-{asset_tag}", equipment_type, location_type, current_holder_id),
        )
        self.conn.commit()

    def _insert_event(
        self,
        asset_tag: str,
        event_type: str,
        event_date: datetime,
        *,
        holder_id: int | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
            VALUES (?, ?, ?, 'test', NULL, '{}', ?);
            """,
            (asset_tag, event_type, event_date.isoformat().replace("+00:00", "Z"), holder_id),
        )
        self.conn.commit()

    def _insert_interval(
        self,
        asset_tag: str,
        *,
        holder_id: int,
        issue_at: datetime,
        elapsed: timedelta,
        equipment_type: str = "laptop",
    ) -> None:
        self._insert_asset(asset_tag, equipment_type=equipment_type)
        self._insert_event(asset_tag, "ISSUE", issue_at, holder_id=holder_id)
        self._insert_event(asset_tag, "RETURN", issue_at + elapsed)

    def _report(self):
        return build_custody_accountability_report(self.conn, generated_at=GENERATED_AT)

    def _dataset(self, measure: str, grouping: str):
        return build_analytics_dataset(self._report(), measure=measure, grouping=grouping)

    def test_total_time_and_transaction_count_by_holder(self) -> None:
        self._insert_holder(1, "Alice Holder", "Mission A")
        self._insert_holder(2, "Bob Holder", "Mission B")
        self._insert_interval("A-1", holder_id=1, issue_at=datetime(2026, 1, 1, tzinfo=timezone.utc), elapsed=timedelta(days=1))
        self._insert_interval("A-2", holder_id=1, issue_at=datetime(2026, 1, 3, tzinfo=timezone.utc), elapsed=timedelta(hours=12))
        self._insert_interval("B-1", holder_id=2, issue_at=datetime(2026, 1, 5, tzinfo=timezone.utc), elapsed=timedelta(days=2))

        totals = build_analytics_dataset(self._report(), measure="total_time_checked_out", grouping="holder")
        transactions = build_analytics_dataset(self._report(), measure="checkout_transactions", grouping="holder")

        self.assertEqual(
            [(row.key, row.label, row.value, row.unit) for row in totals.rows],
            [
                ("holder:1", "Alice Holder (Mission A)", 129600, "seconds"),
                ("holder:2", "Bob Holder (Mission B)", 172800, "seconds"),
            ],
        )
        self.assertEqual(
            [(row.key, row.value, row.unit) for row in transactions.rows],
            [("holder:1", 2, "count"), ("holder:2", 1, "count")],
        )

    def test_assets_by_type_counts_active_assets_only(self) -> None:
        self._insert_asset("LAP-1", equipment_type="laptop")
        self._insert_asset("RTR-1", equipment_type="router")
        self._insert_asset("RTR-2", equipment_type="router")
        self._insert_asset("RET-1", equipment_type="router", location_type="RETIRED")
        for tag in ("LAP-1", "RTR-1", "RTR-2", "RET-1"):
            self._insert_event(tag, "ASSET_CREATED", datetime(2026, 1, 1, tzinfo=timezone.utc))

        dataset = self._dataset("number_of_assets", "asset_type")

        self.assertEqual(
            [(row.key, row.label, row.value) for row in dataset.rows],
            [("asset_type:laptop", "laptop", 1), ("asset_type:router", "router", 2)],
        )

    def test_duration_distribution_bucket_boundaries(self) -> None:
        self._insert_holder(1, "Alice Holder", "Mission A")
        rows = [
            ("B-1", timedelta(hours=7, minutes=59, seconds=59)),
            ("B-2", timedelta(hours=8)),
            ("B-3", timedelta(hours=23, minutes=59, seconds=59)),
            ("B-4", timedelta(days=1)),
            ("B-5", timedelta(days=2, hours=23, minutes=59, seconds=59)),
            ("B-6", timedelta(days=3)),
            ("B-7", timedelta(days=6, hours=23, minutes=59, seconds=59)),
            ("B-8", timedelta(days=7)),
        ]
        for index, (tag, elapsed) in enumerate(rows):
            self._insert_interval(
                tag,
                holder_id=1,
                issue_at=datetime(2026, 1, 1 + index, tzinfo=timezone.utc),
                elapsed=elapsed,
            )

        dataset = self._dataset("checkout_duration", "duration_range")

        self.assertEqual(
            [(row.label, row.value) for row in dataset.rows],
            [
                ("< 8 hours", 1),
                ("8 to <24 hours", 2),
                ("1 to <3 days", 2),
                ("3 to <7 days", 2),
                ("7+ days", 1),
            ],
        )

    def test_current_accountability_totals_reuse_report_values(self) -> None:
        self._insert_holder(1, "Alice Holder", "Mission A")
        self._insert_asset("IN-1", location_type="STORAGE")
        self._insert_event("IN-1", "ASSET_CREATED", datetime(2026, 1, 1, tzinfo=timezone.utc))
        self._insert_asset("OUT-1", location_type="IN_CUSTODY", current_holder_id=1)
        self._insert_event("OUT-1", "ISSUE", datetime(2026, 1, 19, tzinfo=timezone.utc), holder_id=1)
        self._insert_asset("BAD-1", location_type="STORAGE", current_holder_id=1)
        self._insert_event("BAD-1", "RETURN", datetime(2026, 1, 2, tzinfo=timezone.utc))
        report = self._report()

        dataset = build_analytics_dataset(report, measure="current_accountability", grouping="accountability_state")

        self.assertEqual(report.checked_in, 1)
        self.assertEqual(report.checked_out, 1)
        self.assertEqual(report.unresolved, 1)
        self.assertEqual(
            [(row.key, row.label, row.value) for row in dataset.rows],
            [
                ("checked_in", "Checked In", report.checked_in),
                ("checked_out", "Checked Out", report.checked_out),
                ("exceptions_unresolved", "Exceptions / Unresolved", report.unresolved),
            ],
        )

    def test_checkout_activity_groups_by_day_chronologically(self) -> None:
        self._insert_holder(1, "Alice Holder", "Mission A")
        self._insert_interval("DAY-2", holder_id=1, issue_at=datetime(2026, 1, 2, 14, tzinfo=timezone.utc), elapsed=timedelta(hours=1))
        self._insert_interval("DAY-1A", holder_id=1, issue_at=datetime(2026, 1, 1, 8, tzinfo=timezone.utc), elapsed=timedelta(hours=1))
        self._insert_interval("DAY-1B", holder_id=1, issue_at=datetime(2026, 1, 1, 9, tzinfo=timezone.utc), elapsed=timedelta(hours=1))

        dataset = self._dataset("checkout_transactions", "checkout_date")

        self.assertEqual(
            [(row.key, row.label, row.value) for row in dataset.rows],
            [("checkout_date:2026-01-01", "2026-01-01", 2), ("checkout_date:2026-01-02", "2026-01-02", 1)],
        )

    def test_outstanding_interval_uses_existing_custody_model_duration(self) -> None:
        self._insert_holder(1, "Alice Holder", "Mission A")
        self._insert_asset("OUT-1", location_type="IN_CUSTODY", current_holder_id=1)
        self._insert_event("OUT-1", "ISSUE", datetime(2026, 1, 19, 6, tzinfo=timezone.utc), holder_id=1)
        report = self._report()

        totals = build_analytics_dataset(report, measure="total_time_checked_out", grouping="holder")
        buckets = build_analytics_dataset(report, measure="checkout_duration", grouping="duration_range")

        self.assertEqual(report.assets[0].intervals[0].elapsed, timedelta(days=1, hours=6))
        self.assertEqual(totals.rows[0].value, 108000)
        self.assertEqual(
            [(row.label, row.value) for row in buckets.rows],
            [
                ("< 8 hours", 0),
                ("8 to <24 hours", 0),
                ("1 to <3 days", 1),
                ("3 to <7 days", 0),
                ("7+ days", 0),
            ],
        )

    def test_zero_result_datasets_are_clean_and_deterministic(self) -> None:
        first_report = self._report()
        second_report = self._report()

        self.assertEqual(first_report, second_report)
        self.assertEqual(build_analytics_dataset(first_report, measure="total_time_checked_out", grouping="holder").rows, ())
        self.assertEqual(build_analytics_dataset(first_report, measure="checkout_transactions", grouping="checkout_date").rows, ())
        self.assertEqual(
            [(row.label, row.value) for row in build_analytics_dataset(first_report, measure="checkout_duration", grouping="duration_range").rows],
            [
                ("< 8 hours", 0),
                ("8 to <24 hours", 0),
                ("1 to <3 days", 0),
                ("3 to <7 days", 0),
                ("7+ days", 0),
            ],
        )
        self.assertEqual(
            [(row.label, row.value) for row in build_analytics_dataset(first_report, measure="current_accountability", grouping="accountability_state").rows],
            [("Checked In", 0), ("Checked Out", 0), ("Exceptions / Unresolved", 0)],
        )

    def test_output_ordering_is_deterministic(self) -> None:
        self._insert_holder(2, "Bob Holder", "Mission B")
        self._insert_holder(1, "Alice Holder", "Mission A")
        self._insert_interval("RTR-1", holder_id=2, issue_at=datetime(2026, 1, 3, tzinfo=timezone.utc), elapsed=timedelta(hours=1), equipment_type="router")
        self._insert_interval("LAP-1", holder_id=1, issue_at=datetime(2026, 1, 1, tzinfo=timezone.utc), elapsed=timedelta(hours=1), equipment_type="laptop")

        first = build_analytics_dataset(self._report(), measure="total_time_checked_out", grouping="holder")
        second = build_analytics_dataset(self._report(), measure="total_time_checked_out", grouping="holder")
        asset_types = build_analytics_dataset(self._report(), measure="number_of_assets", grouping="asset_type")

        self.assertEqual(first, second)
        self.assertEqual([row.label for row in first.rows], ["Alice Holder (Mission A)", "Bob Holder (Mission B)"])
        self.assertEqual([row.label for row in asset_types.rows], ["laptop", "router"])

    def test_unsupported_measure_grouping_combination_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported custody analytics selection"):
            build_analytics_dataset(self._report(), measure="total_time_checked_out", grouping="asset_type")

    def test_analytics_do_not_modify_database_and_reconcile_with_report(self) -> None:
        self._insert_holder(1, "Alice Holder", "Mission A")
        self._insert_interval("A-1", holder_id=1, issue_at=datetime(2026, 1, 1, tzinfo=timezone.utc), elapsed=timedelta(hours=4))
        self._insert_asset("A-2", location_type="IN_CUSTODY", current_holder_id=1)
        self._insert_event("A-2", "ISSUE", datetime(2026, 1, 19, 12, tzinfo=timezone.utc), holder_id=1)
        report = self._report()
        before = self._snapshot()

        datasets = (
            build_analytics_dataset(report, measure="total_time_checked_out", grouping="holder"),
            build_analytics_dataset(report, measure="checkout_transactions", grouping="holder"),
            build_analytics_dataset(report, measure="current_accountability", grouping="accountability_state"),
        )

        self.assertEqual(before, self._snapshot())
        self.assertEqual(datasets[0].rows[0].value, 100800)
        self.assertEqual(datasets[1].rows[0].value, 2)
        self.assertEqual(datasets[2].rows[0].value + datasets[2].rows[1].value + datasets[2].rows[2].value, report.active_assets)


if __name__ == "__main__":
    unittest.main()
