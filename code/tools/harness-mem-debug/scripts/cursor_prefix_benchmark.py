"""Synthetic-only SQLite prefix benchmark; accepts no native database path."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import platform
import sqlite3
import statistics
import sys
import tempfile
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from harness_mem.adapters.cursor.sqlite_history import PREFIX_SQL  # noqa: E402

SCAN_SQL = (
    "SELECT key, value FROM cursorDiskKV WHERE substr(key, 1, ?) = ? COLLATE BINARY "
    "ORDER BY key COLLATE BINARY"
)


def benchmark(rows: int = 200_000, repeats: int = 7) -> dict:
    if rows < 100 or repeats < 1:
        raise ValueError("rows must be >= 100 and repeats >= 1")
    # Own temporary fixture only. Construction time is excluded from timing.
    with tempfile.TemporaryDirectory(prefix="cursor-prefix-synthetic-") as directory:
        database = Path(directory) / "synthetic.sqlite"
        with closing(sqlite3.connect(database)) as writer:
            writer.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
            writer.executemany("INSERT INTO cursorDiskKV VALUES (?, ?)", (
                (f"bubbleId:{i % 1000:04d}:{i:09d}", '{"synthetic":true}')
                for i in range(rows)
            ))
            writer.commit()
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            prefix = "bubbleId:0001:"
            args = {
                "scan": (len(prefix), prefix),
                "range": (prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1)),
            }
            queries = {"scan": SCAN_SQL, "range": PREFIX_SQL}
            plans = {key: [r[3] for r in db.execute("EXPLAIN QUERY PLAN " + sql, args[key])]
                     for key, sql in queries.items()}
            expected = db.execute(SCAN_SQL, args["scan"]).fetchall()
            assert db.execute(PREFIX_SQL, args["range"]).fetchall() == expected
            assert any("SEARCH" in p and "INDEX" in p for p in plans["range"])
            samples: dict[str, list[float]] = {"scan": [], "range": []}
            # Warm both queries, then alternate order to reduce order bias.
            for repeat in range(repeats):
                for key in (("scan", "range") if repeat % 2 == 0 else ("range", "scan")):
                    start = perf_counter()
                    result = db.execute(queries[key], args[key]).fetchall()
                    samples[key].append((perf_counter() - start) * 1000)
                    assert result == expected
            return {
                "synthetic_only": True, "rows": rows, "matched_rows": len(expected),
                "repeats": repeats, "equivalent": True, "query_plans": plans,
                "baseline": "case-sensitive literal substr prefix scan",
                "timing_scope": "execute + fetchall; warmed connection; fixture setup excluded",
                "milliseconds": {key: {"median": statistics.median(values), "samples": values}
                                 for key, values in samples.items()},
                "sqlite_version": sqlite3.sqlite_version, "python": platform.python_version(),
                "platform": platform.platform(),
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=200_000)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    if args.rows < 100 or args.repeats < 1:
        parser.error("rows must be >= 100 and repeats >= 1")
    print(json.dumps(benchmark(args.rows, args.repeats), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
