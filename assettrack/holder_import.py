from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from assettrack.db import bootstrap_db
from assettrack.holders import _normalize_email

REQUIRED_COLUMNS = ("organization", "name", "email")


@dataclass(frozen=True)
class HolderImportRow:
    row_number: int
    organization: str
    name: str
    email: str


@dataclass(frozen=True)
class HolderImportReport:
    processed: int
    created: int
    updated: int
    errors: tuple[str, ...]

    def summary(self) -> dict[str, int]:
        return {
            "processed": self.processed,
            "created": self.created,
            "updated": self.updated,
            "errors": len(self.errors),
        }


def _normalize_header(name: str | None) -> str:
    return str(name or "").strip().lower()


def _normalize_required_text(value: str | None, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_csv_rows(csv_path: str | Path) -> HolderImportReport | list[HolderImportRow]:
    path = Path(csv_path)
    if not path.exists():
        return HolderImportReport(processed=0, created=0, updated=0, errors=(f"CSV not found: {path}",))

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return HolderImportReport(
                processed=0,
                created=0,
                updated=0,
                errors=("CSV header row is required.",),
            )

        normalized_headers = [_normalize_header(field_name) for field_name in reader.fieldnames]
        if any(not header for header in normalized_headers):
            return HolderImportReport(
                processed=0,
                created=0,
                updated=0,
                errors=("CSV headers must not be blank.",),
            )
        if len(set(normalized_headers)) != len(normalized_headers):
            return HolderImportReport(
                processed=0,
                created=0,
                updated=0,
                errors=("CSV headers must be unique.",),
            )

        missing_columns = [column for column in REQUIRED_COLUMNS if column not in normalized_headers]
        if missing_columns:
            return HolderImportReport(
                processed=0,
                created=0,
                updated=0,
                errors=(f"Missing required CSV columns: {', '.join(missing_columns)}",),
            )

        rows: list[HolderImportRow] = []
        errors: list[str] = []
        seen_emails: dict[str, int] = {}
        processed = 0

        for line_number, raw_row in enumerate(reader, start=2):
            normalized_row = {_normalize_header(key): value for key, value in raw_row.items() if key is not None}
            if None in raw_row:
                errors.append(f"Row {line_number}: malformed CSV row has extra columns.")
                continue
            if any(value is None for value in normalized_row.values()):
                errors.append(f"Row {line_number}: malformed CSV row has missing columns.")
                continue

            if all(not str(value or "").strip() for value in normalized_row.values()):
                continue

            processed += 1

            try:
                organization = _normalize_required_text(normalized_row.get("organization"), field_name="organization")
                name = _normalize_required_text(normalized_row.get("name"), field_name="name")
                email = _normalize_required_text(normalized_row.get("email"), field_name="email")
                normalized_email = _normalize_email(email)
                assert normalized_email is not None
            except ValueError as exc:
                errors.append(f"Row {line_number}: {exc}")
                continue

            previous_row = seen_emails.get(normalized_email)
            if previous_row is not None:
                errors.append(
                    f"Row {line_number}: duplicate email in CSV matches row {previous_row}: {normalized_email}"
                )
                continue

            seen_emails[normalized_email] = line_number
            rows.append(
                HolderImportRow(
                    row_number=line_number,
                    organization=organization,
                    name=name,
                    email=normalized_email,
                )
            )

        if errors:
            return HolderImportReport(processed=processed, created=0, updated=0, errors=tuple(errors))

        return rows


def _organizations_by_name(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT id, name
        FROM organizations;
        """
    ).fetchall()
    return {str(row["name"] or "").strip().lower(): row for row in rows if str(row["name"] or "").strip()}


def _holder_rows_by_email(conn: sqlite3.Connection, emails: set[str]) -> dict[str, list[sqlite3.Row]]:
    holders_by_email: dict[str, list[sqlite3.Row]] = {}
    for email in emails:
        rows = conn.execute(
            """
            SELECT id, holder_type, name, organization, organization_id, email
            FROM holders
            WHERE LOWER(TRIM(COALESCE(email, ''))) = ?;
            """,
            (email,),
        ).fetchall()
        holders_by_email[email] = list(rows)
    return holders_by_email


def _ensure_organization(conn: sqlite3.Connection, organization_name: str, organizations: dict[str, sqlite3.Row]) -> int:
    existing = organizations.get(organization_name.lower())
    if existing is not None:
        return int(existing["id"])

    now_iso = _utc_now_iso()
    cursor = conn.execute(
        """
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES (?, ?, ?);
        """,
        (organization_name, now_iso, now_iso),
    )
    row = conn.execute(
        """
        SELECT id, name
        FROM organizations
        WHERE id = ?;
        """,
        (int(cursor.lastrowid),),
    ).fetchone()
    assert row is not None
    organizations[organization_name.lower()] = row
    return int(row["id"])


def import_holders_csv(csv_path: str | Path, *, db_path: str | Path) -> HolderImportReport:
    parsed = _load_csv_rows(csv_path)
    if isinstance(parsed, HolderImportReport):
        return parsed

    bootstrap_db(Path(db_path))
    conn = sqlite3.connect(Path(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        organizations = _organizations_by_name(conn)
        rows_by_email = _holder_rows_by_email(conn, {row.email for row in parsed})

        duplicate_email_errors: list[str] = []
        for row in parsed:
            matches = rows_by_email.get(row.email, [])
            if len(matches) > 1:
                duplicate_email_errors.append(
                    f"Row {row.row_number}: multiple holders already use email {row.email}; import cannot choose a match."
                )

        if duplicate_email_errors:
            return HolderImportReport(
                processed=len(parsed),
                created=0,
                updated=0,
                errors=tuple(duplicate_email_errors),
            )

        created = 0
        updated = 0

        with conn:
            for row in parsed:
                organization_id = _ensure_organization(conn, row.organization, organizations)
                matches = rows_by_email.get(row.email, [])
                now_iso = _utc_now_iso()

                if not matches:
                    conn.execute(
                        """
                        INSERT INTO holders (
                            holder_type, name, organization, organization_id, email, identifier, contact_info, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?);
                        """,
                        ("PERSON", row.name, row.organization, organization_id, row.email, now_iso, now_iso),
                    )
                    created += 1
                    continue

                holder_id = int(matches[0]["id"])
                conn.execute(
                    """
                    UPDATE holders
                    SET name = ?, organization = ?, organization_id = ?, email = ?, updated_at = ?
                    WHERE id = ?;
                    """,
                    (row.name, row.organization, organization_id, row.email, now_iso, holder_id),
                )
                updated += 1

        return HolderImportReport(processed=len(parsed), created=created, updated=updated, errors=())
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assettrack.holder_import")
    parser.add_argument("csv_path", help="Path to holder CSV file")
    parser.add_argument(
        "--db",
        required=True,
        help="Path to SQLite DB",
    )
    args = parser.parse_args(argv)

    try:
        report = import_holders_csv(args.csv_path, db_path=args.db)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(report.summary(), sort_keys=True))
    if report.errors:
        for error in report.errors:
            print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
