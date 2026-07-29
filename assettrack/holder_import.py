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


@dataclass(frozen=True)
class HolderImportAuditContext:
    actor_user_id: int
    actor_username: str
    source_filename: str


@dataclass(frozen=True)
class HolderImportPreviewRow:
    row_number: int
    category: str
    organization: str
    name: str
    email: str
    before: dict[str, object] | None = None
    after: dict[str, object] | None = None
    problem: str = ""


@dataclass(frozen=True)
class HolderImportPreview:
    processed: int
    rows: tuple[HolderImportPreviewRow, ...]
    errors: tuple[str, ...] = ()

    def summary(self) -> dict[str, int]:
        totals = {
            "processed": self.processed,
            "new": 0,
            "unchanged": 0,
            "updated": 0,
            "duplicate": 0,
            "ambiguous": 0,
            "invalid": 0,
            "blocked": 0,
        }
        for row in self.rows:
            if row.category in totals:
                totals[row.category] += 1
            if row.category in {"duplicate", "ambiguous", "invalid"}:
                totals["blocked"] += 1
        totals["invalid"] += len(self.errors)
        totals["blocked"] += len(self.errors)
        return totals

    @property
    def can_commit(self) -> bool:
        summary = self.summary()
        return self.processed > 0 and summary["blocked"] == 0


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

            if normalized_email not in seen_emails:
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


def _row_after(row: HolderImportRow, organization_id: int | None) -> dict[str, object]:
    return {
        "name": row.name,
        "organization": row.organization,
        "organization_id": organization_id,
        "email": row.email,
    }


def _row_before(holder: sqlite3.Row) -> dict[str, object]:
    return {
        "id": int(holder["id"]),
        "name": holder["name"],
        "organization": holder["organization"],
        "organization_id": holder["organization_id"],
        "email": holder["email"],
    }


def _holder_matches_import(holder: sqlite3.Row, row: HolderImportRow, organization_id: int | None) -> bool:
    return (
        str(holder["name"] or "") == row.name
        and str(holder["organization"] or "") == row.organization
        and (None if holder["organization_id"] is None else int(holder["organization_id"])) == organization_id
        and str(holder["email"] or "").strip().lower() == row.email
    )


def _insert_holder_import_event(
    conn: sqlite3.Connection,
    *,
    audit_context: HolderImportAuditContext,
    created_at: str,
    processed_count: int,
    created_count: int,
    updated_count: int,
) -> None:
    conn.execute(
        """
        INSERT INTO holder_import_events (
            created_at,
            actor_user_id,
            actor_username,
            source_filename,
            processed_count,
            created_count,
            updated_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (
            created_at,
            int(audit_context.actor_user_id),
            str(audit_context.actor_username or "").strip(),
            str(audit_context.source_filename or "").strip(),
            int(processed_count),
            int(created_count),
            int(updated_count),
        ),
    )


def _invalid_preview_row(row_number: int, problem: str, *, organization: str = "", name: str = "", email: str = "") -> HolderImportPreviewRow:
    return HolderImportPreviewRow(
        row_number=row_number,
        category="invalid",
        organization="",
        name="",
        email="",
        problem=problem,
    )



def _load_csv_rows_for_preview(csv_path: str | Path) -> tuple[int, list[HolderImportRow], list[HolderImportPreviewRow]]:
    path = Path(csv_path)
    if not path.exists():
        return 0, [], [_invalid_preview_row(0, f"CSV not found: {path}")]

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return 0, [], [_invalid_preview_row(1, "CSV header row is required.")]

        normalized_headers = [_normalize_header(field_name) for field_name in reader.fieldnames]
        if any(not header for header in normalized_headers):
            return 0, [], [_invalid_preview_row(1, "CSV headers must not be blank.")]
        if len(set(normalized_headers)) != len(normalized_headers):
            return 0, [], [_invalid_preview_row(1, "CSV headers must be unique.")]

        missing_columns = [column for column in REQUIRED_COLUMNS if column not in normalized_headers]
        if missing_columns:
            return 0, [], [_invalid_preview_row(1, f"Missing required CSV columns: {', '.join(missing_columns)}")]

        rows: list[HolderImportRow] = []
        invalid_rows: list[HolderImportPreviewRow] = []
        processed = 0

        for line_number, raw_row in enumerate(reader, start=2):
            normalized_row = {_normalize_header(key): value for key, value in raw_row.items() if key is not None}
            if None in raw_row:
                invalid_rows.append(_invalid_preview_row(line_number, "malformed CSV row has extra columns."))
                continue
            if any(value is None for value in normalized_row.values()):
                invalid_rows.append(_invalid_preview_row(line_number, "malformed CSV row has missing columns."))
                continue

            if all(not str(value or "").strip() for value in normalized_row.values()):
                continue

            processed += 1
            organization = str(normalized_row.get("organization") or "").strip()
            name = str(normalized_row.get("name") or "").strip()
            email = str(normalized_row.get("email") or "").strip()

            try:
                organization = _normalize_required_text(organization, field_name="organization")
                name = _normalize_required_text(name, field_name="name")
                email = _normalize_required_text(email, field_name="email")
                normalized_email = _normalize_email(email)
                assert normalized_email is not None
            except ValueError as exc:
                invalid_rows.append(
                    _invalid_preview_row(
                        line_number,
                        str(exc),
                        organization=organization,
                        name=name,
                        email=email,
                    )
                )
                continue

            rows.append(
                HolderImportRow(
                    row_number=line_number,
                    organization=organization,
                    name=name,
                    email=normalized_email,
                )
            )

        return processed, rows, invalid_rows

def preview_holders_csv(csv_path: str | Path, *, db_path: str | Path) -> HolderImportPreview:
    processed, parsed, invalid_rows = _load_csv_rows_for_preview(csv_path)

    bootstrap_db(Path(db_path))
    conn = sqlite3.connect(Path(db_path))
    conn.row_factory = sqlite3.Row
    try:
        organizations = _organizations_by_name(conn)
        rows_by_email = _holder_rows_by_email(conn, {row.email for row in parsed})
        email_rows: dict[str, list[int]] = {}
        for row in parsed:
            email_rows.setdefault(row.email, []).append(row.row_number)

        preview_rows: list[HolderImportPreviewRow] = list(invalid_rows)
        for row in parsed:
            organization_match = organizations.get(row.organization.lower())
            organization_id = int(organization_match["id"]) if organization_match is not None else None
            after = _row_after(row, organization_id)

            duplicate_rows = email_rows.get(row.email, [])
            if len(duplicate_rows) > 1:
                row_list = ", ".join(str(row_number) for row_number in duplicate_rows)
                preview_rows.append(
                    HolderImportPreviewRow(
                        row_number=row.row_number,
                        category="duplicate",
                        organization=row.organization,
                        name=row.name,
                        email=row.email,
                        after=after,
                        problem=f"Duplicate email in uploaded CSV: {row.email} appears on rows {row_list}.",
                    )
                )
                continue

            matches = rows_by_email.get(row.email, [])
            if len(matches) > 1:
                preview_rows.append(
                    HolderImportPreviewRow(
                        row_number=row.row_number,
                        category="ambiguous",
                        organization=row.organization,
                        name=row.name,
                        email=row.email,
                        after=after,
                        problem=f"Multiple existing holders already use email {row.email}.",
                    )
                )
                continue

            if not matches:
                preview_rows.append(
                    HolderImportPreviewRow(
                        row_number=row.row_number,
                        category="new",
                        organization=row.organization,
                        name=row.name,
                        email=row.email,
                        after=after,
                    )
                )
                continue

            before = _row_before(matches[0])
            category = "unchanged" if _holder_matches_import(matches[0], row, organization_id) else "updated"
            preview_rows.append(
                HolderImportPreviewRow(
                    row_number=row.row_number,
                    category=category,
                    organization=row.organization,
                    name=row.name,
                    email=row.email,
                    before=before,
                    after=after,
                )
            )

        return HolderImportPreview(processed=processed, rows=tuple(sorted(preview_rows, key=lambda row: row.row_number)))
    finally:
        conn.close()


def import_holders_csv(
    csv_path: str | Path,
    *,
    db_path: str | Path,
    audit_context: HolderImportAuditContext | None = None,
) -> HolderImportReport:
    preview = preview_holders_csv(csv_path, db_path=db_path)
    if not preview.can_commit:
        errors = [f"Row {row.row_number}: {row.problem}" for row in preview.rows if row.problem]
        errors.extend(preview.errors)
        if not errors:
            errors.append("No holder rows found.")
        return HolderImportReport(processed=preview.processed, created=0, updated=0, errors=tuple(errors))

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

                if _holder_matches_import(matches[0], row, organization_id):
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

            if audit_context is not None:
                _insert_holder_import_event(
                    conn,
                    audit_context=audit_context,
                    created_at=_utc_now_iso(),
                    processed_count=len(parsed),
                    created_count=created,
                    updated_count=updated,
                )

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
