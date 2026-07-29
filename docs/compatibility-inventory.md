# Compatibility Inventory

This inventory records the compatibility paths reviewed for the combined
0.9.2–0.9.5 release line. It is an ownership and removal ledger, not a second public
API definition. The public MCP contract remains the 27 names in
`harness_mem/mcp/tool_specs.py` and the generated descriptors in
`mcps/harness_mem/tools/`.

## Removal rule

A compatibility path may be removed only when all of the following are true:

1. repository search finds no host, CLI, MCP, migration, rollback, or test
   caller of the compatibility entry;
2. supported persisted data can be opened or migrated without the path;
3. the seven-host smoke suite, MCP surface contract, migration/restart tests,
   and fresh-install checks pass after removal; and
4. any externally consumed file or import has completed a documented
   deprecation window.

An `rg` result by itself is evidence for a removal candidate, not proof that an
editor, installed plugin, old local script, or persisted data no longer depends
on it. No compatibility path was deleted as part of this inventory audit.

## Runtime and import compatibility

| Compatibility path | Current decision | Keep criterion | Remove criterion | Evidence |
|---|---|---|---|---|
| Public and internal handler re-exports from `mcp/tool_handlers.py` | **Keep through the 0.9.x line.** The facade binds dependencies and owns the registry while capability bodies live in bounded modules. Re-exported handlers do not enlarge the public MCP allowlist. | Keep while `server.py`, maintenance orchestration, adapter tests, or older internal imports address the facade. | Replace all facade imports with owned-module imports or an explicit runtime context, then pass handler-boundary, public-surface, maintenance, adapter, and lossless-distill tests. | `harness_mem/mcp/tool_handlers.py`; `harness_mem/mcp/server.py`; `harness_mem/commands/maintenance.py`; `tests/test_mcp_handler_boundaries.py`; `tests/test_mcp_public_surface_contract.py`; `tests/test_lossless_distill_mcp.py`; host adapter tests. |
| Governance callbacks `_get_backend`, `_record_state_event`, and `_distill_candidate_id` | **Keep.** These are narrow callbacks from `governance_handlers.py` to the facade's bound backend, audit owner, and deterministic distill identity owner. | Keep until governance handlers receive the same dependencies without importing the facade and candidate IDs remain replay-idempotent. | Inject a typed runtime context, remove the callbacks, and prove governance audit events, cross-project checks, and distill replay IDs are unchanged. | `harness_mem/mcp/governance_handlers.py`; `harness_mem/mcp/tool_handlers.py`; `tests/test_lossless_distill_mcp.py`; `tests/test_mcp_recall_contract.py`. |
| Cross-capability facade callbacks used by split modules (`_get_backend`, `_observer_data_dir`, `_cost_surface_budgets`, `_record_state_event`, `_run_command_to_payload`, `_gather_project_status`, `tool_ingest_sessions`, `auto_review_candidates`, `dream_auto_tick`) | **Keep.** They preserve the pre-split monkeypatch and dependency-binding seams while the facade stays the single registry owner. | Keep while read/status/distill/dream modules dispatch through `_core` or tests replace facade dependencies. | Replace with one explicit dependency object and update every caller without adding a second registry or scheduler; all compact/full and maintenance tests must remain stable. | `harness_mem/mcp/read_handlers.py`; `status_handlers.py`; `distill_handlers.py`; `dream_handlers.py`; adapter and maintenance tests that call `configure_tool_handler_dependencies`. |
| Incidental private aliases re-exported from the split capability modules | **Removal candidates; retained for 0.9.3.** Repository search found no caller of the facade aliases outside their defining module/facade for the groups below. | Keep during the 0.9.x compatibility window or if an installed integration is found to import one. | Re-run the full removal rule, then remove only the alias import from `tool_handlers.py`; do not remove the owned implementation when another capability module imports it directly. | `harness_mem/mcp/tool_handlers.py` imports listed below; direct owned-module imports in `status_handlers.py` show why alias removal and implementation removal are different decisions. |
| `server.py` dynamic handler re-exports | **Keep.** `server.py` publishes registry handlers into its module globals for older internal imports and tests. | Keep while old imports or test seams may address `harness_mem.mcp.server.tool_*`. | Inventory installed-client usage, migrate callers to `tool_handlers`, and pass stdio/JSON-RPC plus seven-host tests without the globals loop. | `harness_mem/mcp/server.py` (`TOOL_HANDLERS` globals loop); MCP server and public-surface tests. |

The incidental facade aliases currently eligible for a focused follow-up audit
are:

- read constants/types and helpers: `CONTEXT_OUTCOME_VALUES`,
  `VALID_CONTEXT_OUTCOMES`, `VALID_MEMORY_TYPES`,
  `VALID_RETRIEVAL_PROFILES`, `RetrievalProfile`, `_action`,
  `_autopilot_dx_metadata`, `_extract_as_of_hint`, `_is_historical_truth`,
  `_is_superseded_truth`, `_normalize_retrieval_profile`,
  `_resolve_retrieval_profile`, `_retrieval_profile_status`,
  `_search_dx_metadata`, `_temporal_intent_drilldown_hint`,
  `_temporal_intent_mode`, `_temporal_query_action`, `_wake_dx_metadata`, and
  `_with_temporal_intent_hint`;
- status helper: `_bootstrap_status_workspace`;
- dream helpers other than the callback `_run_command_to_payload`:
  `_dream_budget_from_payload`, `_dream_run_summary`, `_highest_risk`,
  `_maintenance_summary`, `_resolve_project_for_dream`, and
  `_resolve_project_root_for_dream`; and
- distill helpers: `_checkpoint_distill_structural_projection`,
  `_distill_job_candidate_ids`, `_load_distill_exchange_windows`,
  `_load_distill_semantic_evidence`, `_recent_project_observations`, and
  `_semantic_review_allows_promotion`.

This list describes unused *facade aliases*. Several underlying helpers still
have direct callers in their owning capability modules and must not be removed
with the aliases.

## Internal MCP orchestration entries

| Entry | Current decision | Keep criterion | Remove criterion | Evidence |
|---|---|---|---|---|
| `set_active_project` | **Keep internal; do not expose publicly.** Directory-first resolution handles normal reads, while MCP session bootstrap, status bootstrap, onboarding, profile, and ingest still update the process-local default. | Keep while any supported flow needs a default project after resolving a workspace. | Remove the tool handler/schema only after no internal JSON-RPC or installed client calls it and every supported flow passes an explicit project context. The lower-level support function is a separate decision. | `harness_mem/mcp/tool_specs.py` (`INTERNAL_MCP_TOOL_NAMES`); `mcp/server.py`; `mcp/status_handlers.py`; `commands/ingest.py`; `commands/onboarding.py`; `commands/profile.py`; `tests/test_mcp_public_surface_contract.py`. |
| `ingest_sessions` | **Keep internal; do not expose publicly.** Distill uses it as its low-level transcript sync step, and host adapter tests exercise client/root resolution and growing revisions. | Keep while `prepare_session_distill` delegates ingestion or diagnostics require direct sync. | Move ingestion behind a non-MCP service boundary and prove Codex, Cursor, Grok, Hermes, Claude Code, OpenCode, and Antigravity distill flows do not call the internal tool. | `harness_mem/mcp/distill_handlers.py`; `mcp/tool_handlers.py`; `mcp/tool_specs.py`; `tests/test_codex_adapter.py`; `test_cursor_adapter.py`; `test_grok_adapter.py`; `test_hermes_adapter.py`; `tests/test_mcp_public_surface_contract.py`. |

The JSON files named `set_active_project.json` and `ingest_sessions.json` under
the Router snapshot directories are not evidence that either entry is public
in harness-mem. `tools/list` is constrained by `PUBLIC_MCP_TOOL_NAMES`, and the
public-surface contract explicitly asserts that both names are absent.

## Legacy readers and migrations

| Compatibility path | Current decision | Keep criterion | Remove criterion | Evidence |
|---|---|---|---|---|
| Storage v2 legacy JSON scan and compatibility read (`scan_legacy_payloads`, `read_compatible_payloads`, and local JSON-store fallbacks) | **Keep for migration and fail-closed recovery.** Canonical SQLite is authoritative after activation; legacy JSON is used to bootstrap, compare, restore, or open a degraded pre-migration store. | Keep while a supported installation can still contain v3 JSON or recovery/rollback needs to compare it with canonical rows. | Announce a storage support cutoff, ship a standalone verified converter, and prove snapshot, rollback, restart recovery, invalid-JSON failure, and newer-canonical-row preservation without runtime readers. | `harness_mem/storage/store_v2_migration.py`; `storage/canonical_store.py`; `storage/local_verbatim_store.py`; `storage/local_structured_store.py`; `storage/local_memory_backend.py`; `tests/test_canonical_store_migration.py`; Doctor recovery tests. |
| Legacy user config JSON fallback | **Keep.** `config.toml` wins; JSON is read only when TOML is absent. | Keep while installations created before TOML migration are supported. | Provide an idempotent config migration with backup and tests, then remove after a documented deprecation window. | `harness_mem/commands/support.py` (`get_config`, `LEGACY_CONFIG_JSON_PATH`); configuration and onboarding callers. |
| Codex archived-rollout adapter and generic legacy import bridge | **Keep as explicit import compatibility, not runtime truth.** These parse external historical inputs into current ingestion/import flows. | Keep while archived Codex sessions and supported draft/export formats remain importable. | Remove only with a replacement converter and fixture-backed proof that supported archives are not stranded. | `harness_mem/adapters/codex/archive_adapter.py`; `harness_mem/tools/import_bridge.py`; adapter/import tests. |
| Literal `status=accepted` governance migration reader | **Keep as explicit governance maintenance.** It previews project-scoped rows, moves them to `pending` or historical `superseded`, records an audit event, and never auto-promotes truth. | Keep while any supported data directory may contain legacy accepted candidates or Doctor can report them. | Remove after a documented migration support window and fixtures prove clean stores, migrated stores, rollback/audit history, and repeated execution remain safe without the reader. | `harness_mem/legacy_governance.py`; `harness_mem/commands/maintenance.py`; `harness_mem/commands/doctor.py`; `tests/test_legacy_governance_migration.py`; `tests/test_doctor_legacy_accepted.py`. |

Generic JSON parsing used by current transcript formats, MCP transport, receipts,
or current SQLite payload serialization is not classified as a legacy reader
merely because it calls `json.loads`.

## Checked-in MCP descriptor directories

| Directory | Current decision | Keep criterion | Remove criterion | Evidence |
|---|---|---|---|---|
| `mcps/harness_mem/tools/` | **Keep canonical and generated.** It contains exactly the 27 public harness-mem descriptors. | Keep while repository MCP descriptors are distributed or verified. | Replace only with an equally testable packaging mechanism generated from `tool_specs.py`. | `harness_mem/mcp/tool_descriptor_export.py`; `tests/test_mcp_exported_tools.py`; `tests/test_mcp_public_surface_contract.py`. |
| `mcps/mcp-router/tools/` and `mcps/mcp_router/tools/` | **Freeze; do not bulk-sync.** The two 170-file directories are byte-equivalent Router snapshots and include tools owned by other servers. Repository Python/tests contain no direct consumer of either directory. | Keep while an editor or workspace integration outside the Python package may consume the checked-in Router snapshots. | Confirm external ownership/consumers, provide a migration note, and pass clean-install Router discovery before deleting one or both directories. Schema changes must never be inferred from these snapshots. | `docs/roadmap/defer.md`; both snapshot directories; repository-wide `rg` finds documentation references but no Python loader; `git diff --no-index` reports the two directories equal. |

The Router namespace name (`mcp__mcp_router__*`) is still a supported way to
reach a live harness-mem server through MCP Router. That runtime alias does not
make the checked-in Router snapshots canonical. Live schemas must come from the
running server; direct descriptors must come from `tool_specs.py` and
`mcps/harness_mem/tools/`.

## 0.9.3 audit result

- No compatibility entry met the full removal rule during this audit.
- The private facade aliases listed above have no repository caller through
  `tool_handlers.py` and are the only concrete removal candidates found.
- `set_active_project`, `ingest_sessions`, governance callbacks, legacy storage
  readers, and the accepted-row migrator all retain verified callers or
  persisted-data responsibilities.
- Router snapshots remain frozen and non-canonical; they must not be used to
  overwrite the 27-tool harness-mem contract.

## 0.9.4 audit result

- Completion and cleanup fields extend the existing distill-job JSON with
  defaults. Old rows remain readable without a SQL migration or pipeline
  version bump and correctly report an unknown historical outcome.
- The public MCP tool count remains 27. Finalize/status add compact result
  fields, but no second tool profile, persistence root, or scheduler.
- Existing post-turn maintenance owns bounded quiet-source retries; the
  default-off cleanup policy does not create an autonomous worker.
- The persistent deletion confirmation is present in CLI help and Bash, Zsh,
  and Fish completion; it does not create another config command or Daily
  workflow.

The 0.9.4 work above ships in the combined 0.9.5 package and tag; no separate
0.9.4 artifact is published.

## 0.9.5 audit result

- Evidence admission extends the three governed candidate payloads with
  optional fields. Legacy rows load with absent fields and keep their previous
  read/governance behavior; no retroactive classification migration is needed.
- `govern_memory`, scoped finalize, candidate detail, Dream audit events, and
  existing status views own the new contract. The public MCP allowlist remains
  exactly 27 names.
- Processed-source cleanup strips transient repository locators from retained
  truth while keeping one-way digests and stable reason codes. It does not add
  another receipt store or cleanup scheduler.
