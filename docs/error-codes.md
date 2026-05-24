# Error Codes

`harness-mem doctor` now emits stable `HM-xxx` codes for actionable setup and maintenance problems. Each code maps to one primary repair action so the output stays short and the docs stay auditable.

| Code | Level | When it appears | Fix command | Notes |
|------|-------|-----------------|-------------|-------|
| `HM-001` | error | Local data directory has not been initialized yet. | `harness-mem quickstart` | Creates the runtime directory and walks through first-time setup. |
| `HM-002` | warning | `doctor` has no project context because there is no active project and none was passed with `-p/--project`. | MCP `set_active_project(project_name="<project-name>")` | Sets the active project so MCP memory tools operate on the same workspace. |
| `HM-003` | warning | Wake-up payload has grown into the `L3` / `L4+` budget range. | `harness-mem purge -p <project-name> --before <yyyy-mm-dd> --category all --dry-run` | Starts with a dry run so you can inspect archival candidates before removing anything from the active path. |
| `HM-101` | error | `[wake] bucket_quota_*` values do not sum to `1.0` (tolerance ±0.001). | edit `~/.harness-mem/config.toml` `[wake]` `bucket_quota_*` (default: `0.5 / 0.5 / 0.0`) | Three values for `semantic / episodic / procedural` must add to one whole budget. v1.6.1+. |
| `HM-102` | error | A single `[wake] bucket_quota_*` value is outside `[0.0, 1.0]` or is not a finite float. | edit `~/.harness-mem/config.toml` `[wake]` `bucket_quota_*` (each value in `[0.0, 1.0]`) | Catches typos like `bucket_quota_episodic = 1.5` before they cascade into wake-up output. v1.6.1+. |
| `HM-201` | warning | Vector index table (`vec_embeddings`) does not exist, is empty, or uses a different embedding model than current config. | `harness-mem maintenance rebuild-vector-index --project <name>` | Rebuilds the persistent vector index with the current embedding model. Hybrid search falls back to FTS until rebuilt. v1.6.2+. |
| `HM-202` | error | SQLite extension loading is disabled in the Python sqlite3 build. | Recompile Python with `--enable-loadable-sqlite-extensions` or use MCP search with FTS-only mode. | `sqlite-vec` requires extension loading support. Most official Python builds support this; custom builds may not. v1.6.2+. |
| `HM-203` | error | Configured embedding model is not in the supported model registry. | Edit `~/.harness-mem/config.toml` `[embedding]` `model_id` to one of: `all-MiniLM-L6-v2`, `bge-small-en-v1.5`, `nomic-embed-text-v1.5`. | Only models in the registry have validated dimensions and licenses. v1.6.2+. |
| `HM-301` | warning | Verbatim exact-evidence trigram index is empty (no observations indexed yet). | `harness-mem maintenance rebuild-verbatim-index --project <name>` | MCP `search_raw` will fall back to slow path until the trigram index is rebuilt. v1.7.3+. |
| `HM-401` | warning | Confirmed rules have not been surfaced in any wake-up for the configured retention window (default 90 days), or have ``usage_count == 0``. | MCP `get_confirmed_rules` -> `reject_rule` or `suggest_supersede` | doctor only flags them; deletion remains a deliberate human action. v1.8+. |

## Output shape

Typical `doctor` output now uses this pattern:

```text
Warning: wake-up context is trending too large for a lightweight resume. (code: HM-003)
Fix: harness-mem purge -p demo --before 2026-02-01 --category all --dry-run
```

The code is the durable lookup key; the fix action is the fastest recovery path.
