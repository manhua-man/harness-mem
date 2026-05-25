"""Diagnostic: did v2.3.0's signal write paths actually fire in real usage?

Reads the real SQLite at $HARNESS_MEM_DATA_DIR (or default) and reports:
  1) whether the new tables exist (proves migrations ran)
  2) row counts in retrieval_signals + metabolism_runs (proves writes happen)
  3) recent confirmed_rules with usage_count + last_surfaced_at (proves
     wake-eligible content exists, so a wake call should have written
     wake_surfaced signals)

Run: python scripts/check_signals.py
"""

from __future__ import annotations

import sqlite3

from harness_mem.commands.support import DEFAULT_DATA_DIR


def main() -> None:
    db = DEFAULT_DATA_DIR / "structured_index.sqlite"
    print(f"DB: {db}")
    print(f"exists: {db.exists()}")
    if not db.exists():
        return

    conn = sqlite3.connect(db)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('retrieval_signals', 'metabolism_runs')"
            ).fetchall()
        ]
        print(f"v2.3.0 tables present: {tables}")
        print()

        print("retrieval_signals by project + type:")
        rows = conn.execute(
            "SELECT project_name, signal_type, COUNT(*) AS n "
            "FROM retrieval_signals "
            "GROUP BY project_name, signal_type "
            "ORDER BY n DESC"
        ).fetchall()
        if not rows:
            print("  (empty)")
        for project, signal_type, count in rows:
            print(f"  {project:25s}  {signal_type:25s}  {count}")
        print()

        print("metabolism_runs by project + status:")
        rows = conn.execute(
            "SELECT project_name, status, COUNT(*) AS n "
            "FROM metabolism_runs "
            "GROUP BY project_name, status "
            "ORDER BY n DESC"
        ).fetchall()
        if not rows:
            print("  (empty)")
        for project, status, count in rows:
            print(f"  {project:25s}  {status:15s}  {count}")
        print()

        print("recent confirmed_rules (newest 5) — should have non-zero usage_count")
        print("if wake has touched them since v2.3.0 went live:")
        rows = conn.execute(
            "SELECT project_name, last_surfaced_at, usage_count, confirmed_at "
            "FROM confirmed_rules "
            "ORDER BY confirmed_at DESC LIMIT 5"
        ).fetchall()
        for project, last_surfaced_at, usage_count, confirmed_at in rows:
            print(
                f"  {project:25s}  usage={usage_count:3d}  "
                f"last_surfaced={last_surfaced_at}  confirmed={confirmed_at}"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
