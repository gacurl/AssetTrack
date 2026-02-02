"""
Smoke test: parse the sample batch CSV and validate required fields.
Run:
    python3 scripts/validate_fixture.py
"""

from assettrack.ingest.parser import parse_batch
from assettrack.ingest.validator import validate_rows


def main() -> None:
    path = "docs/fixtures/sample_batch.csv"
    parsed = parse_batch(path)
    report = validate_rows(parsed)

    print(f"File: {path}")
    print(f"Rows: {len(report['rows'])}")
    print(f"Valid: {report['valid']}")

    # Print any errors
    for row in report["rows"]:
        if row["errors"]:
            print(f"\nRow {row['row_number']} errors:")
            for err in row["errors"]:
                print(f"  - {err}")


if __name__ == "__main__":
    main()
