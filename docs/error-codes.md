# Error Codes

`harness-mem doctor` now emits stable `HM-xxx` codes for actionable setup and maintenance problems. Each code maps to one primary repair command so the terminal output stays short and the docs stay auditable.

| Code | Level | When it appears | Fix command | Notes |
|------|-------|-----------------|-------------|-------|
| `HM-001` | error | Local data directory has not been initialized yet. | `harness-mem quickstart` | Creates the runtime directory and walks through first-time setup. |
| `HM-002` | warning | `doctor` has no project context because there is no active project and none was passed with `-p/--project`. | `harness-mem use <project-name>` | Sets the active project so `doctor`, `ingest`, `wake`, and `search` can operate on the same workspace. |
| `HM-003` | warning | Wake-up payload has grown into the `L3` / `L4+` budget range. | `harness-mem purge -p <project-name> --before <yyyy-mm-dd> --category all --dry-run` | Starts with a dry run so you can inspect archival candidates before removing anything from the active path. |

## Output shape

Typical `doctor` output now uses this pattern:

```text
Warning: wake-up context is trending too large for a lightweight resume. (code: HM-003)
Fix: harness-mem purge -p demo --before 2026-02-01 --category all --dry-run
```

The code is the durable lookup key; the fix command is the fastest recovery path.
