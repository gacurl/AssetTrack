# assettrack/ingest/cli.py

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from assettrack.ingest.committer import BatchCommitError, commit_batch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assettrack.ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)

    commit = sub.add_parser("commit", help="Commit validated preview rows as a unit")
    commit.add_argument("--db", required=True, help="Path to SQLite DB")
    commit.add_argument(
        "--rows-json",
        required=True,
        help="Path to JSON file containing validated rows (list of dicts)",
    )

    args = parser.parse_args(argv)

    if args.cmd == "commit":
        rows_path = Path(args.rows_json)
        rows = json.loads(rows_path.read_text(encoding="utf-8"))

        try:
            result = commit_batch(rows, db_path=args.db)
        except BatchCommitError as e:
            print(f"Commit failed: {e}", file=sys.stderr)
            return 2

        print(json.dumps({"committed_count": result.committed_count}))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())