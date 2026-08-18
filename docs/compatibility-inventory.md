# Compatibility Inventory

This inventory records the compatibility boundary after the 0.9.6 convergence
pass. It is an ownership ledger, not a second API definition.

## Public contract

- MCP exposes exactly the 27 names in `PUBLIC_MCP_TOOL_NAMES`.
- `_SCHEMAS`, `TOOL_CLUSTERS`, and `build_tool_handlers()` contain exactly those
  same 27 names. The former 17 low-level orchestration schemas are retired and
  retained only as a denylist against accidental re-exposure.
- The stable Daily action set remains `wake -> search -> distill -> review ->
  dream`; it maps onto, but does not replace, the internal architecture
  `session intake and lifecycle -> extraction -> verification -> assimilation
  -> retrieval/use`. The seven host actions are `status`, `wake`, `search`,
  `search-all`, `distill`, `review`, and `dream`.
- The operator CLI is limited to quickstart, doctor, public config policy,
  integration repair, and explicit maintenance.

## Removed in 0.9.6

| Surface | Replacement | Evidence gate |
|---|---|---|
| Hidden MCP schemas and registry entries for low-level suggest/confirm/reject, direct ingest/project mutation, and handoff helpers | `govern_memory`, `prepare_session_distill`, and directory-first project resolution | Registry equality tests and generated-descriptor tests require exactly 27 public entries. |
| Six host-specific hook installer commands | `harness-mem integration hooks sync --client <host|all>` | CLI parser, per-host/all-host dispatch, completion, and seven-host integration tests. |
| Daily-work CLI modules for candidate, handoff, profile, search, and status flows | MCP plus the seven host-native Daily actions | Public CLI surface and documentation lifecycle tests. |
| Doctor's weak-link experiment recommendation | Normal retrieval quality/status diagnostics | Doctor output contract rejects the retired recommendation. |
| Public writes to 25 low-level tuning keys | Ten user-facing policy keys; existing values remain readable | Config list/set and merged-loader compatibility tests. |
| Two stale, duplicate MCP Router aggregate snapshot directories (340 files) | Live `mcp__mcp_router__*` namespace discovery plus canonical `mcps/harness_mem/tools/` descriptors | Repository/package consumer audit, byte-equality audit, absence guard, and old tags for historical retrieval. |

Removal does not delete stored memory, config files, or migration readers. The
private governance implementation still owns the individual operations used by
the composite `govern_memory` handler; those functions are implementation
details, not MCP tools.

## Config compatibility

The public writable policy surface is:

```text
capture.enabled
capture.private_tags
capture.ignore_clients
capture.ignore_session_ids
capture.ignore_source_globs
transcript.retention_days
distill.auto.enabled
distill.autonomous.enabled
distill.delete_source_after_complete
archive_distill.enabled
archive_distill.batch_size
archive_distill.daily_limit
archive_distill.order
archive_distill.project_scope
archive_distill.unresolved_project
archive_distill.warn_tokens
archive_distill.warn_seconds
archive_distill.require_answer_packet
archive_distill.report_promotions
dream.auto.enabled
```

Typed runtime tuning remains readable during the 0.9.x compatibility window
and is shown only by `config list --detail runtime`; it is not writable through
`harness-mem config`. Legacy
`~/.harness-mem/config.json`, user TOML, and project TOML use one merge order:
legacy JSON base, user TOML override, project TOML override. Existing unknown
extras remain preserved when a public key is edited.

## Runtime compatibility retained

| Path | Why it remains | Removal gate |
|---|---|---|
| Governance helper functions behind `govern_memory` | The composite handler and automatic review share their audited implementations. | Replace only with an equivalent typed service while preserving state events, idempotency, and governance tests. |
| Facade dependency callbacks used by read/status/distill/dream modules | They provide one backend/runtime binding and established test seams. | Introduce one typed runtime context without adding a second registry or scheduler, then pass full parity tests. |
| Storage v2 legacy JSON readers and migration recovery | Deprecated in 0.9.6; supported through 0.9.x so existing entity JSON remains readable without an implicit authority change. | Not before both 1.0.0 and 2027-01-31; converter shipped, Doctor canonical verification clean, and release notes explicitly announcing removal are also required. |
| Literal `status=accepted` governance migration | Older data may still contain accepted candidates. | End the documented migration window only after fixture-backed repeated migration and audit tests. |
| Codex archived-rollout and supported import bridges | Historical inputs must remain importable through explicit maintenance. `codex-archive` is a Codex source/client alias with a dedicated parser, not an eighth host or capability row. | Provide a replacement converter with fixture parity. |

## Descriptors and Router aliases

`mcps/harness_mem/tools/` is canonical and generated from the 27 runtime
schemas. The duplicate `mcps/mcp-router` and `mcps/mcp_router` aggregate
snapshots were removed in 0.9.6 after proving they were byte-identical,
unpackaged, unconsumed in the repository, and materially stale. Live
`mcp__mcp_router__*` aliases remain supported; they are discovered from the
running Router and never depended on those files.

## 0.9.6 result

- Public schema, handler, cluster, descriptor, hint, and serializer contracts
  now agree on one 27-tool surface.
- Host repair and public config each have one visible path.
- The former `local_structured_store.py`, `read_handlers.py`, and `doctor.py`
  monoliths are bounded facades/orchestrators with source-level size and
  ownership guardrails. Their domain modules preserve the same imports and
  public runtime behavior.
- Legacy entity JSON remains readable through the documented cutoff. Startup
  no longer silently changes authority; explicit global migration is
  receipt-first and rollback-aware.
- Processed-source cleanup and privacy erase remain separate implementations.
  Privacy erase additionally attempts bounded native-host deletion and reports
  partial failure for shared or unsafe sources.
- New guardrails fail if retired tool names, historical schema-version labels,
  or non-public handlers return to a public contract.
