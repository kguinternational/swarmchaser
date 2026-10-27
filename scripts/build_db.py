#!/usr/bin/env python3
"""Build or refresh the Swarmchaser SQLite warehouse.

    python scripts/build_db.py                  # ingest everything, refresh FTS
    python scripts/build_db.py --stats          # show what is in the database
    python scripts/build_db.py --search "mint wallet"
    python scripts/build_db.py --sql "SELECT dataset, COUNT(*) FROM posts GROUP BY 1"
    python scripts/build_db.py --reset          # drop and rebuild from scratch
    python scripts/build_db.py --skip-traces    # fast build without the 90 MB corpus

The database lives at ``data/swarmchaser.db`` by default (gitignored) and is safe
to rebuild at any time: every table is upserted on its natural key.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.swarm import store  # noqa: E402


def _human_bytes(size: float | None) -> str:
    if not size:
        return "?"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def print_stats(conn) -> None:
    data = store.stats(conn)
    meta = data["meta"]
    print(f"database : {conn.execute('PRAGMA database_list').fetchone()[2]}")
    print(f"size     : {_human_bytes(data['db_bytes'])}")
    print(f"schema   : v{meta.get('schema_version')}  built {meta.get('built_at')}")
    print("\ntables")
    for table, count in data["tables"].items():
        if count:
            print(f"  {table:<24} {count:>10,}")

    if data["datasets"]:
        print("\narchive slices")
        print(f"  {'dataset':<16}{'posts':>10}{'agents':>10}{'first post':>22}{'last post':>22}")
        for row in data["datasets"]:
            print(
                f"  {row['dataset']:<16}{row['posts']:>10,}{row['posting_agents']:>10,}"
                f"{str(row['first_post'])[:19]:>22}{str(row['last_post'])[:19]:>22}"
            )

    if data["swarm_kinds"]:
        print("\nswarms by kind")
        for row in data["swarm_kinds"]:
            print(
                f"  {row['dataset']:<16}{row['kind'][:46]:<48}"
                f"{row['swarms']:>5}{row['agents'] or 0:>9,}{row['posts'] or 0:>9,}"
            )


def print_rows(rows: list[dict]) -> None:
    if not rows:
        print("no rows")
        return
    width = max(len(key) for row in rows for key in row)
    for row in rows:
        print("  ".join(f"{key}={value}" for key, value in row.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(store.DEFAULT_DB), help="database path (default: data/swarmchaser.db)")
    parser.add_argument("--data", default=str(store.DATA_DIR), help="raw archive root")
    parser.add_argument("--reports", default=str(store.REPORTS_DIR), help="reports root")
    parser.add_argument("--reset", action="store_true", help="drop every table before ingesting")
    parser.add_argument("--skip-traces", action="store_true", help="skip data/swarmtraces/*.jsonl")
    parser.add_argument("--no-fts", action="store_true", help="skip full-text index rebuild")
    parser.add_argument("--stats", action="store_true", help="print warehouse stats and exit")
    parser.add_argument("--search", metavar="TEXT", help="full-text search and exit")
    parser.add_argument("--sql", metavar="SQL", help="run a read-only query and exit (JSON output)")
    parser.add_argument("--vacuum", action="store_true", help="compact the database after ingest")
    args = parser.parse_args(argv)

    db_path = Path(args.db).expanduser()
    conn = store.connect(db_path)

    if args.stats:
        print_stats(conn)
        return 0

    if args.search:
        rows = store.search(conn, args.search, limit=25)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0 if rows else 1

    if args.sql:
        try:
            rows = store.query(conn, args.sql)
        except Exception as exc:  # surface SQL errors plainly
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.reset:
        store.reset(conn)
    else:
        store.init_schema(conn)

    data_dir = Path(args.data).expanduser()
    reports_dir = Path(args.reports).expanduser()
    totals: dict[str, int] = {}

    def add(key: str, value: int) -> None:
        totals[key] = totals.get(key, 0) + value

    for folder, dataset in (("moltbook", "moltbook"), ("moltbook_feb", "moltbook_feb")):
        root = data_dir / folder
        if not root.exists():
            continue
        print(f"ingesting {root.name} ...", file=sys.stderr)
        counts = store.ingest_moltbook(conn, root, dataset)
        for key, value in counts.items():
            add(f"raw_{key}", value)

    traces = data_dir / "swarmtraces" / "redacted.jsonl"
    if traces.exists() and not args.skip_traces:
        print(f"ingesting {traces} ...", file=sys.stderr)
        add("swarmtraces", store.ingest_swarmtraces(conn, traces))

    if reports_dir.exists():
        print(f"ingesting {reports_dir} ...", file=sys.stderr)
        for key, value in store.ingest_reports(conn, reports_dir, data_dir).items():
            add(key, value)

    if not args.no_fts:
        print("rebuilding full-text indexes ...", file=sys.stderr)
        store.refresh_fts(conn)

    conn.execute(
        "INSERT INTO meta(key, value) VALUES('last_build', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (store._now(),),
    )
    conn.commit()
    if args.vacuum:
        conn.execute("VACUUM")
    conn.commit()

    print(json.dumps({"db": str(db_path), "ingested": totals}, indent=2))
    print()
    print_stats(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
