"""Copy the database to a frozen snapshot that every eval run uses.

Gold answers come from running the gold SQL, so they change whenever the data
changes. Scoring every run against one fixed copy keeps results from
different days comparable.

Output: the snapshot next to the live database (gitignored, read-only), and
        eval/snapshot.json, which records its SHA-256 hash and a few counts.
        The harness checks the hash before a run and stores it in the results.

Usage:
    python scripts/freeze_snapshot.py [--source PATH] [--name NAME]
"""

import argparse
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import duckdb

DEFAULT_SOURCE = Path("data/warehouse/garmin.duckdb")
MANIFEST = Path("eval/snapshot.json")


def sha256_of(path):
    """Return the SHA-256 hash of a file as hex text."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--name", default=f"garmin_eval_{date.today().isoformat()}.duckdb")
    args = parser.parse_args()

    snapshot = args.source.parent / args.name
    if snapshot.exists():
        raise SystemExit(f"{snapshot} already exists; a snapshot is never overwritten")
    # A write-ahead log holds changes not yet in the main file, so a plain
    # copy of the main file would miss them.
    if Path(f"{args.source}.wal").exists():
        raise SystemExit(f"{args.source}.wal exists; close open connections first")

    shutil.copyfile(args.source, snapshot)
    snapshot.chmod(0o444)

    con = duckdb.connect(str(snapshot), read_only=True)
    try:
        rows, first, last = con.execute(
            "SELECT count(*), CAST(min(start_time_local) AS DATE), "
            "CAST(max(start_time_local) AS DATE) FROM activities"
        ).fetchone()
    finally:
        con.close()

    manifest = {
        "snapshot": str(snapshot),
        "source": str(args.source),
        "created": date.today().isoformat(),
        "sha256": sha256_of(snapshot),
        "duckdb_version": duckdb.__version__,
        "activities_rows": rows,
        "first_activity": first.isoformat(),
        "last_activity": last.isoformat(),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
