# file: tests/test_dashboard.py
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import assettrack.db as db
from assettrack.dashboard import (
    MAX_DASHBOARD_RECENT_ACTIVITY,
    build_dashboard_data,
)
from assettrack.event_types import issue_event_type_values
from assettrack.intake import app as intake_app
from tests.auth_test_utils import create_test_user, login_session


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp_dir.name) / "assettrack.db"
        self.conn = db.get_connection()
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_tag TEXT NOT NULL UNIQUE,
                serial_number TEXT NULL,
                manufacturer TEXT NULL,
                equipment_type TEXT NOT NULL,
                building TEXT NULL,
                room TEXT NULL,
                model TEXT NULL,
                model_code TEXT NULL,
                notes TEXT NULL,
                building_room TEXT NULL,
                custody_state TEXT NOT NULL,
                accountability_status TEXT NOT NULL,
                condition TEXT NOT NULL,
                created_date TEXT NOT NULL,
                updated_date TEXT NULL,
                location_type TEXT NULL,
                current_holder_id INTEGER NULL,
                home_slot_id INTEGER NULL
            );
            """
        )
        self.conn.commit()
        intake_app.app.testing = True
        self.client = intake_app.app.test_client()
        operator_user_id = create_test_user(username="operator", password="op-pass", role="operator")
        login_session(self.client, operator_user_id)

    def _login_admin(self) -> None:
        admin_user_id = create_test_user(username="admin", password="admin-pass", role="admin")
        login_session(self.client, admin_user_id)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def _insert_holder(self, holder_id: int, name: str, *, organization: str | None = None) -> None:
        now = "2026-01-01T00:00:00Z"
        self.conn.execute(
            """
            INSERT INTO holders (id, holder_type, name, organization, identifier, contact_info, created_at, updated_at)
            VALUES (?, 'PERSON', ?, ?, NULL, NULL, ?, ?);
            """,
            (holder_id, name, organization, now, now),
        )

    def _insert_asset(
        self,
        asset_tag: str,
        *,
        location_type: str,
        home_slot_id: int | None = None,
        current_holder_id: int | None = None,
        equipment_type: str = "laptop",
        building: str = "HQ",
        room: str = "100",
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO assets (
                asset_tag,
                serial_number,
                manufacturer,
                equipment_type,
                building,
                room,
                building_room,
                custody_state,
                accountability_status,
                condition,
                created_date,
                updated_date,
                location_type,
                current_holder_id,
                home_slot_id
            )
            VALUES (?, ?, 'Dell', ?, ?, ?, ?, 'in_stock', 'accountable', 'serviceable', '2026-01-01', '2026-01-01T00:00:00Z', ?, ?, ?);
            """,
            (
                asset_tag,
                f"SN-{asset_tag}",
                equipment_type,
                building,
                room,
                f"{building}/{room}" if building and room else "",
                location_type,
                current_holder_id,
                home_slot_id,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_slot(self, slot_id: int, case_name: str, slot_position: int) -> None:
        self.conn.execute(
            """
            INSERT INTO slots (id, case_name, slot_position, current_asset_tag)
            VALUES (?, ?, ?, NULL);
            """,
            (slot_id, case_name, slot_position),
        )

    def _insert_issue_event(self, asset_tag: str, event_date: str, *, legacy: bool = False) -> None:
        issue_values = issue_event_type_values()
        event_type = issue_values[1] if legacy else issue_values[0]
        self.conn.execute(
            """
            INSERT INTO asset_events (asset_tag, event_type, event_date, actor, notes, payload, holder_id)
            VALUES (?, ?, ?, 'tester', NULL, NULL, NULL);
            """,
            (asset_tag, event_type, event_date),
        )

    def _insert_event(
        self,
        asset_tag: str,
        event_type: str,
        event_date: str,
        *,
        holder_id: int | None = None,
        supersedes_event_id: int | None = None,
        correction_reason: str | None = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO asset_events (
                asset_tag,
                event_type,
                event_date,
                actor,
                notes,
                payload,
                holder_id,
                supersedes_event_id,
                correction_reason
            )
            VALUES (?, ?, ?, 'tester', NULL, NULL, ?, ?, ?);
            """,
            (asset_tag, event_type, event_date, holder_id, supersedes_event_id, correction_reason),
        )
        return int(cursor.lastrowid)

    def _replace_slot_occupancy_without_unique_constraints(self) -> None:
        self.conn.execute("DROP TABLE slot_occupancy;")
        self.conn.execute(
            """
            CREATE TABLE slot_occupancy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slot_id INTEGER NOT NULL,
                asset_id INTEGER NOT NULL,
                assigned_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def test_dashboard_route_smoke_renders_summary_sections(self) -> None:
        self._insert_holder(1, "Alex Holder", organization="CISR")
        self._insert_slot(10, "CASE-A", 1)
        storage_asset_id = self._insert_asset("AT-STORED", location_type="STORAGE", home_slot_id=10)
        self._insert_asset("AT-UNSLOT", location_type="STORAGE", home_slot_id=None)
        self._insert_asset("AT-CUST", location_type="IN_CUSTODY", current_holder_id=1)
        self._insert_asset("AT-DISP", location_type="DISPOSED")
        self.conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (10, ?, '2026-01-01T00:00:00Z');
            """,
            (storage_asset_id,),
        )
        self._insert_issue_event("AT-CUST", "2025-12-01T00:00:00Z")
        self.conn.commit()

        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Dashboard", response.data)
        self.assertNotIn(b"Dashboard Summary Metrics", response.data)
        self.assertNotIn(b"At a Glance", response.data)
        self.assertIn(b"Assets Out", response.data)
        self.assertIn(b"Assets Remaining", response.data)
        self.assertIn(b"Total Assets", response.data)
        self.assertNotIn(b"Issue Assets", response.data)
        self.assertNotIn(b"Return Assets", response.data)
        self.assertIn(b'href="/issue">Issue</a>', response.data)
        self.assertIn(b'href="/return">Return</a>', response.data)
        self.assertNotIn(b"class=\"dashboard-primary-card dashboard-action-card dashboard-action-link\"", response.data)
        self.assertNotIn(b"Open Issue Workflow", response.data)
        self.assertNotIn(b"Open Return Workflow", response.data)
        self.assertNotIn(b'class="action-secondary" href="/issue">Issue Assets</a>', response.data)
        self.assertNotIn(b'class="action-secondary" href="/return">Return Assets</a>', response.data)
        self.assertIn(b"Asset Location Map", response.data)
        self.assertIn(b"Asset location map is read-only.", response.data)
        self.assertNotIn(b"Use this map for rough inventory orientation only.", response.data)
        self.assertNotIn(b"Field Operational Custody Map", response.data)
        self.assertNotIn(b"Custody Map", response.data)
        self.assertIn(b"Mission Area: CISR", response.data)
        self.assertNotIn(b"Mission Area: <a", response.data)
        self.assertNotIn(b"Thread:", response.data)
        self.assertIn(b"Asset Domain", response.data)
        self.assertNotIn(b"Operational Domain", response.data)
        self.assertIn(b"SysAdmins", response.data)
        self.assertIn(b"Alex Holder", response.data)
        self.assertIn(b"Building: HQ", response.data)
        self.assertIn(b"Asset Domain: SysAdmins", response.data)
        self.assertIn(b"Custody Holder:", response.data)
        self.assertIn(b'<a class="nav-link" href="/assets/search">Asset Search</a>', response.data)
        self.assertIn(
            b'<a class="nav-link" href="/assets/history?asset_tag=AT-CUST&amp;return_to=/dashboard"><code>AT-CUST</code></a>',
            response.data,
        )
        self.assertNotIn(b"Asset: <code>AT-CUST</code>", response.data)
        self.assertGreaterEqual(response.data.count(b'class="disclosure-section custody-map-node"'), 4)
        self.assertIn(b'id="problems-panel"', response.data)
        self.assertIn(b'id="problems-panel" open', response.data)
        self.assertNotIn(b"Available Space by Case", response.data)
        self.assertNotIn(b"Recent Activity", response.data)
        self.assertIn(b"Problems", response.data)
        self.assertIn(b"1 unslotted, 1 over 30 days, 0 conflicts", response.data)
        self.assertNotIn(b"0 open", response.data)
        self.assertNotIn(b"FULL", response.data)
        self.assertNotIn(b"0 / 1", response.data)
        self.assertIn(b"AT-UNSLOT", response.data)
        self.assertIn(b"AT-CUST", response.data)
        self.assertIn(b'href="/holders/1"', response.data)
        self.assertIn(b'href="/report">Current Custody</a>', response.data)
        self.assertNotIn(b"Open manual holder follow-up", response.data)
        self.assertIn(b'href="/dashboard/cases"', response.data)
        self.assertIn(b"Case Status", response.data)
        self.assertIn(b"Asset Search", response.data)
        self.assertIn(b'href="/report"', response.data)
        self.assertNotIn(b"Workflow Shortcuts", response.data)
        self.assertNotIn(b'href="/issue/preview">Issue</a>', response.data)

    def test_first_run_guide_shows_for_admin_when_no_operational_data(self) -> None:
        self._login_admin()

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"First-run deployment guide", response.data)
        self.assertIn(b"No assets, holders, storage, or asset events exist yet.", response.data)
        self.assertIn(b"Assets may remain Unslotted. Storage can be created and assigned later.", response.data)
        self.assertIn(b"Recommended", response.data)
        self.assertIn(b"Optional", response.data)
        self.assertIn(b"Deferrable", response.data)
        self.assertIn(b'href="/admin/assets/import"', response.data)
        self.assertIn(b"Import inventory", response.data)
        self.assertIn(b'href="/admin/holders/import"', response.data)
        self.assertIn(b"Import Holders", response.data)
        self.assertIn(b'href="/holders/new?return_to=/dashboard"', response.data)
        self.assertIn(b"Add one Holder", response.data)
        self.assertIn(b"Create a holder before issuing assets.", response.data)
        self.assertIn(b'href="/admin/slots/provision"', response.data)
        self.assertIn(b"Create storage", response.data)
        self.assertIn(b'href="/admin/assets/new"', response.data)
        self.assertIn(b"Add one asset", response.data)
        self.assertIn(b'href="#dashboard-main"', response.data)
        self.assertIn(b"Continue to Dashboard", response.data)
        self.assertIn(b"Assets Out", response.data)
        self.assertIn(b"No active assets in the asset location map.", response.data)
        for table_name in ("assets", "holders", "slots", "asset_events"):
            row_count = int(self.conn.execute(f"SELECT COUNT(*) FROM {table_name};").fetchone()[0])
            self.assertEqual(row_count, 0)

    def test_first_run_guide_hides_after_creating_one_holder(self) -> None:
        self._login_admin()

        holder_form = self.client.get("/holders/new?return_to=/dashboard")
        self.assertEqual(holder_form.status_code, 200)
        self.assertIn(b"Create Holder", holder_form.data)
        self.assertIn(b'name="return_to" value="/dashboard"', holder_form.data)

        response = self.client.post(
            "/holders/new",
            data={
                "name": "First Holder",
                "organization_id": "1",
                "email": "first@example.org",
                "return_to": "/dashboard",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"First-run deployment guide", response.data)
        self.assertNotIn(b"Import inventory", response.data)
        self.assertIn(b"Assets Out", response.data)
        holder_count = int(self.conn.execute("SELECT COUNT(*) FROM holders;").fetchone()[0])
        self.assertEqual(holder_count, 1)
    def test_dashboard_empty_states_are_operator_facing(self) -> None:
        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"First-run deployment guide", response.data)
        self.assertNotIn(b"Import inventory", response.data)
        self.assertNotIn(b'href="/admin/assets/import"', response.data)
        self.assertNotIn(b"At a Glance", response.data)
        self.assertIn(b"Assets Out", response.data)
        self.assertNotIn(b"Issue Assets", response.data)
        self.assertNotIn(b"Return Assets", response.data)
        self.assertIn(b'href="/issue">Issue</a>', response.data)
        self.assertIn(b'href="/return">Return</a>', response.data)
        self.assertNotIn(b"Open Issue Workflow", response.data)
        self.assertNotIn(b"Open Return Workflow", response.data)
        self.assertIn(b"Asset Location Map", response.data)
        self.assertIn(b"Asset location map is read-only.", response.data)
        self.assertIn(b"No active assets in the asset location map.", response.data)
        self.assertIn(b'id="problems-panel"', response.data)
        self.assertNotIn(b'id="problems-panel" open', response.data)
        self.assertIn(b"Asset Search", response.data)
        self.assertNotIn(b"No case data available.", response.data)
        self.assertNotIn(b"No recent activity.", response.data)
        self.assertIn(b"No current problems.", response.data)
        self.assertIn(b"No unslotted assets.", response.data)
        self.assertIn(b"No overdue in-custody assets.", response.data)
        self.assertIn(b"No slot conflicts detected.", response.data)

    def test_available_space_summary_flags_and_case_links(self) -> None:
        self._insert_slot(1, "CASE-B", 1)
        self._insert_slot(2, "CASE-B", 2)
        self._insert_slot(3, "CASE-B", 3)
        self._insert_slot(4, "CASE-B", 4)
        self._insert_slot(10, "CASE-C", 1)
        self._insert_slot(11, "CASE-C", 2)
        self._insert_slot(12, "CASE-C", 3)
        self._insert_slot(13, "CASE-C", 4)
        self._insert_slot(14, "CASE-C", 5)
        self._insert_slot(15, "CASE-D", 1)
        self._insert_slot(16, "CASE-D", 2)
        self._insert_slot(20, "CASE-A", 1)
        self._insert_slot(21, "CASE-A", 2)

        asset_a1 = self._insert_asset("AT-A1", location_type="STORAGE", home_slot_id=20)
        asset_a2 = self._insert_asset("AT-A2", location_type="STORAGE", home_slot_id=21)
        asset_b1 = self._insert_asset("AT-B1", location_type="STORAGE", home_slot_id=1)
        asset_c1 = self._insert_asset("AT-C1", location_type="STORAGE", home_slot_id=10)
        asset_c2 = self._insert_asset("AT-C2", location_type="STORAGE", home_slot_id=11)
        asset_c3 = self._insert_asset("AT-C3", location_type="STORAGE", home_slot_id=12)
        asset_c4 = self._insert_asset("AT-C4", location_type="STORAGE", home_slot_id=13)

        self.conn.executemany(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (?, ?, '2026-01-01T00:00:00Z');
            """,
            [
                (20, asset_a1),
                (21, asset_a2),
                (1, asset_b1),
                (10, asset_c1),
                (11, asset_c2),
                (12, asset_c3),
                (13, asset_c4),
            ],
        )
        self.conn.commit()

        data = build_dashboard_data(self.conn, custody_days_threshold=30)
        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Available Space by Case", response.data)
        self.assertNotIn(b"Based on open slots. Best available case: CASE-B with 3 open", response.data)
        self.assertNotIn(b'href="/dashboard/cases/CASE-A">CASE-A</a>', response.data)
        self.assertNotIn(b'href="/dashboard/cases/CASE-B">CASE-B</a>', response.data)
        self.assertNotIn(b'href="/dashboard/cases/CASE-C">CASE-C</a>', response.data)
        self.assertNotIn(b'href="/dashboard/cases/CASE-D">CASE-D</a>', response.data)
        rows_by_case = {row["case_name"]: row for row in data["snapshots"]["case_utilization"]}
        self.assertEqual(rows_by_case["CASE-A"]["empty_slots"], 0)
        self.assertEqual(rows_by_case["CASE-A"]["status_flag"], "FULL")
        self.assertEqual(rows_by_case["CASE-B"]["empty_slots"], 3)
        self.assertEqual(rows_by_case["CASE-B"]["status_flag"], "OPEN")
        self.assertEqual(rows_by_case["CASE-C"]["empty_slots"], 1)
        self.assertEqual(rows_by_case["CASE-C"]["status_flag"], "LOW")
        self.assertEqual(rows_by_case["CASE-D"]["empty_slots"], 2)
        self.assertNotIn(b"OPEN - Use now", response.data)
        self.assertNotIn(b"LOW - Getting tight", response.data)
        self.assertNotIn(b"FULL - No space", response.data)
        self.assertNotIn(b"Stoplight Status", response.data)
        self.assertNotIn(b"0 / 2", response.data)
        self.assertNotIn(b'status-dot full', response.data)
        self.assertNotIn(b'status-dot low', response.data)

    def test_available_space_cases_sort_naturally_by_case_number(self) -> None:
        for slot_id, case_name in enumerate(
            ["CASE-13", "CASE-2", "CASE-111", "CASE-1", "CASE-16", "ALPHA"],
            start=1,
        ):
            self._insert_slot(slot_id, case_name, 1)
        self.conn.commit()

        data = build_dashboard_data(self.conn, custody_days_threshold=30)
        response = self.client.get("/dashboard")

        self.assertEqual(
            [row["case_name"] for row in data["snapshots"]["case_utilization"]],
            ["CASE-1", "CASE-2", "CASE-13", "CASE-16", "CASE-111", "ALPHA"],
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Available Space by Case", response.data)
        self.assertNotIn(b'href="/dashboard/cases/CASE-16">CASE-16</a>', response.data)
        self.assertNotIn(b'href="/dashboard/cases/CASE-111">CASE-111</a>', response.data)

    def test_dashboard_case_snapshot_keeps_all_cases_and_best_available_case(self) -> None:
        slot_id = 1
        cases: list[tuple[str, int]] = []
        for index in range(1, 16):
            occupied_slots = 0 if index == 6 else 1 + (index % 5)
            cases.append((f"CASE-{index}", occupied_slots))

        for case_name, occupied_slots in cases:
            for _ in range(10):
                self._insert_slot(slot_id, case_name, slot_id)
                if occupied_slots > 0:
                    asset_id = self._insert_asset(f"AT-{case_name}-{slot_id}", location_type="STORAGE", home_slot_id=slot_id)
                    self.conn.execute(
                        """
                        INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
                        VALUES (?, ?, '2026-01-01T00:00:00Z');
                        """,
                        (slot_id, asset_id),
                    )
                    occupied_slots -= 1
                slot_id += 1
        self.conn.commit()

        data = build_dashboard_data(self.conn, custody_days_threshold=30)
        rendered = self.client.get("/dashboard")

        self.assertEqual(len(data["snapshots"]["case_utilization"]), 15)
        self.assertEqual(
            [row["case_name"] for row in data["snapshots"]["case_utilization"]],
            [f"CASE-{index}" for index in range(1, 16)],
        )
        self.assertEqual(
            next(row for row in data["snapshots"]["case_utilization"] if row["case_name"] == "CASE-6")["empty_slots"],
            10,
        )
        self.assertEqual(rendered.status_code, 200)
        self.assertNotIn(b"Available Space by Case", rendered.data)
        self.assertNotIn(b"Based on open slots. Best available case: CASE-6 with 10 open", rendered.data)
        self.assertNotIn(b'href="/dashboard/cases/CASE-6">CASE-6</a>', rendered.data)
        self.assertNotIn(b'href="/dashboard/cases/CASE-15">CASE-15</a>', rendered.data)

    def test_dashboard_metrics_use_distinct_and_most_recent_issue_event(self) -> None:
        self._replace_slot_occupancy_without_unique_constraints()
        self._insert_holder(1, "Alpha")
        self._insert_holder(2, "Bravo")

        self._insert_slot(1, "CASE-X", 1)
        self._insert_slot(2, "CASE-X", 2)

        asset_old = self._insert_asset("AT-OLD", location_type="IN_CUSTODY", current_holder_id=1)
        asset_recent = self._insert_asset("AT-RECENT", location_type="IN_CUSTODY", current_holder_id=1)
        asset_noevent = self._insert_asset("AT-NOEVENT", location_type="IN_CUSTODY", current_holder_id=2)
        asset_storage = self._insert_asset("AT-STORAGE", location_type="STORAGE", home_slot_id=2)

        self.conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES
                (1, ?, '2026-01-01T00:00:00Z'),
                (1, ?, '2026-01-02T00:00:00Z'),
                (2, ?, '2026-01-03T00:00:00Z');
            """,
            (asset_old, asset_recent, asset_storage),
        )

        self._insert_issue_event("AT-OLD", "2026-01-01T00:00:00Z")
        self._insert_issue_event("AT-RECENT", "2026-01-01T00:00:00Z", legacy=True)
        self._insert_issue_event("AT-RECENT", "2026-02-10T00:00:00Z")
        self.conn.commit()

        data = build_dashboard_data(
            self.conn,
            custody_days_threshold=30,
            now_utc=datetime(2026, 2, 20, 0, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(data["summary"]["slots"]["occupied_slots"], 2)
        self.assertEqual(data["summary"]["exceptions"]["slot_conflicts"], 1)
        self.assertEqual(data["summary"]["exceptions"]["in_custody_over_threshold"], 1)

        overdue_rows = data["snapshots"]["exceptions"]["in_custody_over_threshold"]
        self.assertEqual(len(overdue_rows), 1)
        self.assertEqual(overdue_rows[0]["asset_tag"], "AT-OLD")
        self.assertEqual(overdue_rows[0]["days_out"], 50)

    def test_slot_utilization_does_not_round_up_to_100_unless_full(self) -> None:
        for slot_id in range(1, 245):
            self._insert_slot(slot_id, "CASE-Z", slot_id)

        for slot_id in range(1, 244):
            asset_id = self._insert_asset(f"AT-{slot_id}", location_type="STORAGE", home_slot_id=slot_id)
            self.conn.execute(
                """
                INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
                VALUES (?, ?, '2026-01-01T00:00:00Z');
                """,
                (slot_id, asset_id),
            )
        self.conn.commit()

        data = build_dashboard_data(self.conn, custody_days_threshold=30)

        self.assertEqual(data["summary"]["slots"]["total_slots"], 244)
        self.assertEqual(data["summary"]["slots"]["occupied_slots"], 243)
        self.assertEqual(data["summary"]["slots"]["empty_slots"], 1)
        self.assertEqual(data["summary"]["slots"]["utilization_percent"], "99.6")

    def test_slot_utilization_displays_100_only_when_full(self) -> None:
        self._insert_slot(1, "CASE-FULL", 1)
        self._insert_slot(2, "CASE-FULL", 2)
        asset_a = self._insert_asset("AT-FULL-1", location_type="STORAGE", home_slot_id=1)
        asset_b = self._insert_asset("AT-FULL-2", location_type="STORAGE", home_slot_id=2)
        self.conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES
                (1, ?, '2026-01-01T00:00:00Z'),
                (2, ?, '2026-01-01T00:00:00Z');
            """,
            (asset_a, asset_b),
        )
        self.conn.commit()

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"FULL", response.data)
        self.assertNotIn(b"FULL - No space", response.data)

    def test_root_redirects_to_dashboard_when_logged_in(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue((resp.headers.get("Location") or "").endswith("/dashboard"))

    def test_dashboard_holder_name_links_to_existing_holder_detail_page(self) -> None:
        self._insert_holder(1, "Alex Holder", organization="CISR")
        self._insert_asset("AT-CUST-1", location_type="IN_CUSTODY", current_holder_id=1)
        self.conn.commit()

        dashboard_response = self.client.get("/dashboard")

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn(b'href="/holders/1"', dashboard_response.data)
        self.assertIn(b"Alex Holder", dashboard_response.data)

        holder_detail = self.client.get("/holders/1")
        self.assertEqual(holder_detail.status_code, 200)
        self.assertIn(b"Alex Holder", holder_detail.data)
        self.assertIn(b"AT-CUST-1", holder_detail.data)

    def test_dashboard_holder_name_falls_back_to_plain_text_when_holder_detail_missing(self) -> None:
        self._insert_asset("AT-CUST-PLAIN", location_type="IN_CUSTODY", current_holder_id=77)
        self.conn.commit()

        dashboard_response = self.client.get("/dashboard")

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn(b"ID 77", dashboard_response.data)
        self.assertNotIn(b'href="/holders/77"', dashboard_response.data)

    def test_recent_activity_renders_newest_events_first_with_holder_and_return_fallback(self) -> None:
        self._insert_holder(1, "Alpha Holder")
        self._insert_event("AT-1", "ISSUE", "2026-01-01T10:00:00Z", holder_id=1)
        self._insert_event("AT-2", "RETURN", "2026-01-01T11:00:00Z")
        self._insert_event("AT-3", "ASSET_CREATED", "2026-01-01T12:00:00Z")
        self.conn.commit()

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Recent Activity", response.data)
        self.assertNotIn(b"Added", response.data)
        self.assertNotIn(b"Returned to storage", response.data)
        self.assertNotIn(b"Issued to", response.data)
        self.assertNotIn(b"Alpha Holder", response.data)
        self.assertNotIn(b"2026-01-01 12:00 UTC", response.data)
        self.assertNotIn(b"When (UTC)", response.data)

        data = build_dashboard_data(self.conn, custody_days_threshold=30)
        self.assertEqual(
            [row["event_label"] for row in data["snapshots"]["recent_activity"]],
            ["Added", "Returned to storage", "Issued to"],
        )
        self.assertEqual(data["snapshots"]["recent_activity"][2]["holder_label"], "Alpha Holder (Ad Hoc)")

    def test_recent_activity_excludes_superseded_events(self) -> None:
        original_id = self._insert_event("AT-1", "ISSUE", "2026-01-01T10:00:00Z")
        self._insert_event(
            "AT-1",
            "RETURN",
            "2026-01-01T11:00:00Z",
            supersedes_event_id=original_id,
            correction_reason="Correction",
        )
        self.conn.commit()

        data = build_dashboard_data(self.conn, custody_days_threshold=30)

        self.assertEqual(len(data["snapshots"]["recent_activity"]), 1)
        self.assertEqual(data["snapshots"]["recent_activity"][0]["event_type"], "RETURN")
        self.assertEqual(data["snapshots"]["recent_activity"][0]["asset_tag"], "AT-1")

    def test_recent_activity_snapshot_is_bounded(self) -> None:
        for index in range(MAX_DASHBOARD_RECENT_ACTIVITY + 5):
            self._insert_event(
                f"AT-{index}",
                "RETURN",
                f"2026-01-{(index % 28) + 1:02d}T12:00:00Z",
            )
        self.conn.commit()

        data = build_dashboard_data(self.conn, custody_days_threshold=30)

        self.assertEqual(len(data["snapshots"]["recent_activity"]), MAX_DASHBOARD_RECENT_ACTIVITY)

    def test_asset_location_map_groups_non_disposed_assets_by_domain_mission_building_holder(self) -> None:
        self._insert_holder(1, "Alex Holder", organization="CISR")
        self._insert_slot(10, "CASE-STORAGE", 1)
        self._insert_asset(
            "AT-LAPTOP",
            location_type="IN_CUSTODY",
            current_holder_id=1,
            equipment_type="laptop",
            building="HQ North",
            room="210",
        )
        stored_switch_id = self._insert_asset(
            "AT-STORED-SWITCH",
            location_type="STORAGE",
            home_slot_id=10,
            equipment_type="switch",
            building="HQ North",
            room="Closet",
        )
        self.conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (10, ?, '2026-01-01T00:00:00Z');
            """,
            (stored_switch_id,),
        )
        self._insert_asset(
            "AT-UNSLOTTED-ROUTER",
            location_type="STORAGE",
            home_slot_id=None,
            equipment_type="router",
            building="HQ North",
            room="Closet",
        )
        self._insert_asset(
            "AT-UNKNOWN",
            location_type="STORAGE",
            equipment_type="other",
            building="",
            room="",
        )
        self._insert_asset(
            "AT-DISPOSED",
            location_type="DISPOSED",
            current_holder_id=1,
            equipment_type="laptop",
            building="HQ North",
            room="210",
        )
        self.conn.commit()

        data = build_dashboard_data(self.conn, custody_days_threshold=30)

        custody_map = data["snapshots"]["custody_map"]
        self.assertEqual(custody_map["asset_count"], 4)
        self.assertEqual([domain["label"] for domain in custody_map["domains"]], ["SysAdmins", "Network", "Unclassified Asset"])

        sysadmins_domain = custody_map["domains"][0]
        self.assertEqual([mission_area["label"] for mission_area in sysadmins_domain["mission_areas"]], ["CISR"])
        cisr_mission = sysadmins_domain["mission_areas"][0]
        self.assertEqual([building["label"] for building in cisr_mission["buildings"]], ["HQ North"])
        sysadmins_holder = cisr_mission["buildings"][0]["holders"][0]
        self.assertEqual(sysadmins_holder["label"], "Alex Holder")
        self.assertEqual(sysadmins_holder["assets"][0]["asset_tag"], "AT-LAPTOP")
        self.assertEqual(sysadmins_holder["assets"][0]["equipment_type_label"], "Laptop")
        self.assertEqual(sysadmins_holder["assets"][0]["storage_display"], "")

        network_domain = custody_map["domains"][1]
        self.assertEqual([mission_area["label"] for mission_area in network_domain["mission_areas"]], ["No Mission Area Recorded"])
        no_mission = network_domain["mission_areas"][0]
        self.assertEqual([building["label"] for building in no_mission["buildings"]], ["HQ North"])
        network_holder = no_mission["buildings"][0]["holders"][0]
        self.assertEqual(network_holder["label"], "No Custody Holder")
        self.assertEqual(
            [asset["asset_tag"] for asset in network_holder["assets"]],
            ["AT-STORED-SWITCH", "AT-UNSLOTTED-ROUTER"],
        )
        self.assertEqual(
            [asset["equipment_type_label"] for asset in network_holder["assets"]],
            ["Switch", "Router"],
        )
        self.assertEqual(
            [asset["storage_display"] for asset in network_holder["assets"]],
            ["Stored in CASE-STORAGE, Slot 1", "Unslotted"],
        )
        self.assertEqual(network_holder["assets"][0]["storage_case_name"], "CASE-STORAGE")
        self.assertEqual(network_holder["assets"][0]["storage_slot_position"], 1)
        self.assertEqual(network_holder["assets"][1]["storage_case_name"], "")
        self.assertIsNone(network_holder["assets"][1]["storage_slot_position"])

        unclassified_domain = custody_map["domains"][2]
        unclassified_mission = unclassified_domain["mission_areas"][0]
        self.assertEqual(unclassified_mission["label"], "No Mission Area Recorded")
        self.assertEqual(unclassified_mission["buildings"][0]["label"], "No Building Recorded")
        self.assertEqual(unclassified_mission["buildings"][0]["holders"][0]["label"], "No Custody Holder")
        self.assertEqual(unclassified_mission["buildings"][0]["holders"][0]["assets"][0]["asset_tag"], "AT-UNKNOWN")

        displayed_assets = []
        for domain in custody_map["domains"]:
            for mission_area in domain["mission_areas"]:
                for building in mission_area["buildings"]:
                    for holder in building["holders"]:
                        displayed_assets.extend(asset["asset_tag"] for asset in holder["assets"])
        self.assertEqual(sorted(displayed_assets), ["AT-LAPTOP", "AT-STORED-SWITCH", "AT-UNKNOWN", "AT-UNSLOTTED-ROUTER"])
        self.assertEqual(len(displayed_assets), len(set(displayed_assets)))
        self.assertEqual(len(displayed_assets), custody_map["asset_count"])

    def test_custody_map_render_is_collapsible_at_each_hierarchy_level(self) -> None:
        self._insert_holder(1, "Alex Holder", organization="CISR")
        self._insert_slot(20, "CASE-MAP", 7)
        self._insert_asset(
            "AT-LAPTOP",
            location_type="IN_CUSTODY",
            current_holder_id=1,
            equipment_type="laptop",
            building="HQ North",
            room="210",
        )
        stored_switch_id = self._insert_asset(
            "AT-SWITCH",
            location_type="STORAGE",
            home_slot_id=20,
            equipment_type="switch",
            building="HQ North",
            room="Closet",
        )
        self.conn.execute(
            """
            INSERT INTO slot_occupancy (slot_id, asset_id, assigned_at)
            VALUES (20, ?, '2026-01-01T00:00:00Z');
            """,
            (stored_switch_id,),
        )
        self._insert_asset(
            "AT-UNSLOTTED",
            location_type="STORAGE",
            equipment_type="router",
            building="HQ North",
            room="Closet",
        )
        self.conn.commit()

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'aria-label="Asset location map"', response.data)
        self.assertIn(b"Mission Area: CISR", response.data)
        self.assertIn(b"Mission Area: No Mission Area Recorded", response.data)
        self.assertNotIn(b"Mission Area: <a", response.data)
        self.assertNotIn(b"Thread:", response.data)
        self.assertIn(b"Building: HQ North", response.data)
        self.assertIn(b"Asset Domain: SysAdmins", response.data)
        self.assertIn(b"Asset Domain: Network", response.data)
        self.assertIn(b"Custody Holder:", response.data)
        self.assertIn(b'<a class="nav-link" href="/assets/search">Asset Search</a>', response.data)
        self.assertIn(
            b'<a class="nav-link" href="/assets/history?asset_tag=AT-LAPTOP&amp;return_to=/dashboard"><code>AT-LAPTOP</code></a>',
            response.data,
        )
        self.assertIn(
            b'<a class="nav-link" href="/assets/history?asset_tag=AT-SWITCH&amp;return_to=/dashboard"><code>AT-SWITCH</code></a>',
            response.data,
        )
        self.assertIn(
            b'<a class="nav-link" href="/dashboard/cases/CASE-MAP?return_to=/dashboard">Stored in CASE-MAP, Slot 7</a>',
            response.data,
        )
        self.assertIn(b"Unslotted", response.data)
        self.assertGreaterEqual(response.data.count(b'class="disclosure-section custody-map-node"'), 4)
        self.assertIn(b'class="custody-map-asset"', response.data)
