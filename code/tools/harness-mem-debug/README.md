# harness-mem debug

`harness-mem-debug` is a repository-only, read-only inspector for runtime
evidence. It is not a `hm` command, MCP tool, or Python console entry point.

```text
python code/tools/harness-mem-debug/scripts/debug.py inspect --run-id <run-id>
python code/tools/harness-mem-debug/scripts/debug.py events --run-id <run-id> --follow
python code/tools/harness-mem-debug/scripts/debug.py bundle --run-id <run-id> --output <path>
```

Use `--job-id`, `--trigger-id`, or `--latest --project-root <path>` when a
legacy receipt is the only available evidence. Reports default to hashes,
references, and bounded error summaries; raw transcript chunks are included
only when `bundle` is called with `--include-source`.

The runtime event ledger is `debug/run-events.ndjson` below the configured
harness-mem data directory. Event-write failures are best effort and are
reported as evidence gaps by the inspector; they never change memory
business results.

`completed` records the operation's returned state, not proof of a knowledge
write. Provider events surround actual calls. `readback_verified` is emitted
only after reported writes pass both current-store and ordinary-search checks.
Wrappers do not infer source loading, Answer Gate, or SQLite commit events;
missing boundary evidence stays missing, including no-write and replay paths.
Nested calls use task-local context; subprocess parent references are passed
in the child environment without modifying the parent process environment.

## Cursor SQLite schema diagnostics

```text
python code/tools/harness-mem-debug/scripts/debug.py cursor-schema --database /explicit/path/state.vscdb
```

This developer-only command calls `inspect_sqlite_schema` with the explicitly
supplied path. It never discovers Cursor profiles or opens the memory backend.
JSON output contains the path, readability status, tables, columns, and key
namespace counts; it does not contain stored values or session text. A column
named `value` may appear in schema metadata. Reading an unfamiliar schema is
not proof that session intake supports that schema.

Exit codes: `0` means the schema was readable; `2` means invalid command usage
(including a missing `--database`); `3` means unreadable evidence, including a
missing, corrupt, or locked database. An unreadable database produces a JSON
report with `status: unreadable`. A missing file is never created. Existing
`inspect`, `events`, and `bundle` behavior is unchanged.

## Synthetic prefix benchmark

```text
python code/tools/harness-mem-debug/scripts/cursor_prefix_benchmark.py --rows 200000 --repeats 7
```

The benchmark accepts no database path. It creates and removes its own
temporary synthetic SQLite fixture, then opens it read-only. It checks exact
ordered key/value equivalence and `EXPLAIN QUERY PLAN` before timing. The
baseline uses case-sensitive literal `substr` prefix matching (not SQLite's
default case-insensitive/wildcard `LIKE` semantics); the other query is the
adapter's binary indexed range query. Both queries are warmed, execution order
alternates, and timing includes execution plus fetching all results, excluding
fixture creation. JSON output includes every timing sample and environment.
There is no speed threshold or promised multiplier.

Measured on 2026-09-24, Windows 11 build 26200, Python 3.13.7, SQLite 3.50.4:

| Synthetic workload | Result |
| --- | --- |
| Total rows / selected rows | 200,000 / 200 |
| Measured repetitions | 7 per query |
| Exact ordered results | Equal on every repetition |
| Baseline plan | `SCAN cursorDiskKV USING INDEX sqlite_autoindex_cursorDiskKV_1` |
| Range plan | `SEARCH cursorDiskKV USING INDEX sqlite_autoindex_cursorDiskKV_1 (key>? AND key<?)` |
| Baseline median (min–max) | 15.171 ms (14.047–19.260 ms) |
| Range median (min–max) | 0.772 ms (0.147–0.924 ms) |

This run shows an indexed range search with equivalent results and lower
measured latency for this synthetic distribution. It does not establish
performance for real Cursor histories, cold caches, other selectivities, or
concurrent writers.
