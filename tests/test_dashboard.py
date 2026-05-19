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
        self.assertIn(b"Issue Assets", response.data)
        self.assertIn(b"Return Assets", response.data)
        self.assertIn(b"Open Issue Workflow", response.data)
        self.assertIn(b"Open Return Workflow", response.data)
        self.assertIn(b"Custody Map", response.data)
        self.assertNotIn(b"Field Operational Custody Map", response.data)
        self.assertIn(b"Thread: CISR", response.data)
        self.assertNotIn(b"Thread: <a", response.data)
        self.assertIn(b"Operational Domain", response.data)
        self.assertIn(b"SysAdmins", response.data)
        self.assertIn(b"Alex Holder", response.data)
        self.assertIn(b"Building: HQ", response.data)
        self.assertIn(b"Operational Domain: SysAdmins", response.data)
        self.assertIn(b"Custody Holder:", response.data)
        self.assertIn(b"Asset: <code>AT-CUST</code>", response.data)
        self.assertGreaterEqual(response.data.count(b'class="disclosure-section custody-map-node"'), 4)
        self.assertIn(b'id="problems-panel"', response.data)
        self.assertIn(b'id="problems-panel" open', response.data)
        self.assertIn(b"Available Space by Case", response.data)
        self.assertIn(b"Recent Activity", response.data)
        self.assertIn(b"Problems", response.data)
        self.assertIn(b"No cases have available space.", response.data)
        self.assertIn(b"1 unslotted, 1 over 30 days, 0 conflicts", response.data)
        self.assertIn(b"0 open", response.data)
        self.assertIn(b"FULL", response.data)
        self.assertNotIn(b"0 / 1", response.data)
        self.assertIn(b"AT-UNSLOT", response.data)
        self.assertIn(b"Issued to", response.data)
        self.assertIn(b"AT-CUST", response.data)
        self.assertIn(b'href="/holders/1"', response.data)
        self.assertIn(b'href="/report">View Current Custody</a>', response.data)
        self.assertNotIn(b"Open holder follow-up", response.data)
        self.assertIn(b'href="/dashboard/cases"', response.data)
        self.assertIn(b'href="/report"', response.data)
        self.assertNotIn(b"Workflow Shortcuts", response.data)
        self.assertNotIn(b'href="/issue/preview">Issue</a>', response.data)

    def test_dashboard_empty_states_are_operator_facing(self) -> None:
        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"At a Glance", response.data)
        self.assertIn(b"Assets Out", response.data)
        self.assertIn(b"Open Issue Workflow", response.data)
        self.assertIn(b"Open Return Workflow", response.data)
        self.assertIn(b"Custody Map", response.data)
        self.assertIn(b"No active assets in the custody map.", response.data)
        self.assertIn(b'id="problems-panel"', response.data)
        self.assertNotIn(b'id="problems-panel" open', response.data)
        self.assertIn(b"Search assets", response.data)
        self.assertIn(b"No case data available.", response.data)
        self.assertIn(b"No recent activity.", response.data)
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

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Based on open slots. Best available case: CASE-B with 3 open", response.data)
        self.assertIn(b'href="/dashboard/cases/CASE-A">CASE-A</a>', response.data)
        self.assertIn(b"0 open", response.data)
        self.assertIn(b"FULL", response.data)
        self.assertIn(b'href="/dashboard/cases/CASE-B">CASE-B</a>', response.data)
        self.assertIn(b"3 open", response.data)
        self.assertIn(b"OPEN", response.data)
        self.assertIn(b'href="/dashboard/cases/CASE-C">CASE-C</a>', response.data)
        self.assertIn(b"1 open", response.data)
        self.assertIn(b"LOW", response.data)
        self.assertIn(b'href="/dashboard/cases/CASE-D">CASE-D</a>', response.data)
        self.assertIn(b"2 open", response.data)
        self.assertNotIn(b"OPEN - Use now", response.data)
        self.assertNotIn(b"LOW - Getting tight", response.data)
        self.assertNotIn(b"FULL - No space", response.data)
        self.assertNotIn(b"Stoplight Status", response.data)
        self.assertNotIn(b"0 / 2", response.data)
        self.assertIn(b".status-dot.full { background: #c2410c; }", response.data)
        self.assertIn(b".status-dot.low { background: #f59e0b; }", response.data)
        self.assertIn(b".status-dot.open { background: #16a34a; }", response.data)
        self.assertIn(b'status-dot full', response.data)
        self.assertIn(b'status-dot low', response.data)

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
        self.assertLess(
            response.data.index(b'href="/dashboard/cases/CASE-16">CASE-16</a>'),
            response.data.index(b'href="/dashboard/cases/CASE-111">CASE-111</a>'),
        )

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
        self.assertIn(b"Based on open slots. Best available case: CASE-6 with 10 open", rendered.data)
        self.assertIn(b'href="/dashboard/cases/CASE-6">CASE-6</a>', rendered.data)
        self.assertIn(b'href="/dashboard/cases/CASE-15">CASE-15</a>', rendered.data)

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
        self.assertIn(b"Recent Activity", response.data)
        self.assertIn(b"Added", response.data)
        self.assertIn(b"Returned to storage", response.data)
        self.assertIn(b"Issued to", response.data)
        self.assertIn(b"Alpha Holder", response.data)
        self.assertIn(b"\xe2\x80\x94", response.data)
        self.assertIn(b"2026-01-01 12:00 UTC", response.data)
        self.assertIn(b"When (UTC)", response.data)

        created_index = response.data.index(b"Added")
        returned_index = response.data.index(b"Returned to storage")
        issued_index = response.data.index(b"Issued to")
        self.assertLess(created_index, returned_index)
        self.assertLess(returned_index, issued_index)

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

    def test_custody_map_groups_assets_by_building_domain_holder_with_fallbacks(self) -> None:
        self._insert_holder(1, "Alex Holder", organization="CISR")
        self._insert_asset(
            "AT-LAPTOP",
            location_type="IN_CUSTODY",
            current_holder_id=1,
            equipment_type="laptop",
            building="HQ North",
            room="210",
        )
        self._insert_asset(
            "AT-SWITCH",
            location_type="STORAGE",
            equipment_type="switch",
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
        self.conn.commit()

        data = build_dashboard_data(self.conn, custody_days_threshold=30)

        custody_map = data["snapshots"]["custody_map"]
        self.assertEqual(custody_map["asset_count"], 3)
        self.assertEqual([thread["label"] for thread in custody_map["threads"]], ["CISR", "Unknown Thread"])

        cisr_thread = custody_map["threads"][0]
        self.assertEqual([building["label"] for building in cisr_thread["buildings"]], ["HQ North"])

        hq_building = cisr_thread["buildings"][0]
        self.assertEqual([domain["label"] for domain in hq_building["domains"]], ["SysAdmins"])
        sysadmins_holder = hq_building["domains"][0]["holders"][0]
        self.assertEqual(sysadmins_holder["label"], "Alex Holder")
        self.assertEqual(sysadmins_holder["assets"][0]["asset_tag"], "AT-LAPTOP")
        self.assertEqual(sysadmins_holder["assets"][0]["equipment_type_label"], "Laptop")

        unknown_thread = custody_map["threads"][1]
        self.assertEqual([building["label"] for building in unknown_thread["buildings"]], ["HQ North", "Unknown Building"])

        hq_building = unknown_thread["buildings"][0]
        self.assertEqual([domain["label"] for domain in hq_building["domains"]], ["Network"])
        network_holder = hq_building["domains"][0]["holders"][0]
        self.assertEqual(network_holder["label"], "Unassigned Holder")
        self.assertEqual(network_holder["assets"][0]["asset_tag"], "AT-SWITCH")

        unknown_building = unknown_thread["buildings"][1]
        self.assertEqual(unknown_building["domains"][0]["label"], "Unclassified Asset")
        self.assertEqual(unknown_building["domains"][0]["holders"][0]["assets"][0]["asset_tag"], "AT-UNKNOWN")

    def test_custody_map_render_is_collapsible_at_each_hierarchy_level(self) -> None:
        self._insert_holder(1, "Alex Holder", organization="CISR")
        self._insert_asset(
            "AT-LAPTOP",
            location_type="IN_CUSTODY",
            current_holder_id=1,
            equipment_type="laptop",
            building="HQ North",
            room="210",
        )
        self._insert_asset(
            "AT-SWITCH",
            location_type="STORAGE",
            equipment_type="switch",
            building="HQ North",
            room="Closet",
        )
        self.conn.commit()

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'aria-label="Custody map"', response.data)
        self.assertIn(b"Thread: CISR", response.data)
        self.assertIn(b"Thread: Unknown Thread", response.data)
        self.assertNotIn(b"Thread: <a", response.data)
        self.assertIn(b"Building: HQ North", response.data)
        self.assertIn(b"Operational Domain: SysAdmins", response.data)
        self.assertIn(b"Operational Domain: Network", response.data)
        self.assertIn(b"Custody Holder:", response.data)
        self.assertIn(b"Asset: <code>AT-LAPTOP</code>", response.data)
        self.assertIn(b"Asset: <code>AT-SWITCH</code>", response.data)
        self.assertGreaterEqual(response.data.count(b'class="disclosure-section custody-map-node"'), 4)
        self.assertIn(b'class="custody-map-asset"', response.data)
