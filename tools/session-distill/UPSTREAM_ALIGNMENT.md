# Upstream Alignment

Reviewed against
[`manhua-man/session-distill-skills`](https://github.com/manhua-man/session-distill-skills)
commit `723cd0df27a1fc3205423b69d224204e04138e66` (2026-07-15).

## Scope

The upstream repository is a multi-host suite. It carries separate Claude,
Cursor, Codex, Grok, Hermes, OpenCode, and Antigravity implementations plus
`contracts/*.yaml`. Its `session-distill/` subdirectory is specifically the
Claude implementation; it does not define the whole upstream product.

harness-mem deliberately uses a different runtime shape: host-specific
Adapters feed one transcript ledger and one MCP lifecycle. We align mechanisms
and evidence contracts, not the upstream per-host CLI layout or note-first
promotion destinations.

## Mechanisms Aligned

| Upstream mechanism | harness-mem owner |
|---|---|
| Content-derived source revision | `harness_mem/transcript_chunking.py` and transcript store |
| Complete ordered chunks and rebuildability | transcript chunking/store tests |
| Durable chunk leases and checkpoints | session distill store and MCP submit operation |
| Requeue when a session grows | adapter snapshot + fair scan scheduler |
| Mandatory final-session review | `finalize_session_distill` semantic gate |
| Stable candidate identity | source revision + pipeline version + kind + normalized claim |
| Per-host growth and project-isolation evidence | seven Adapter contract/fixture tests |

## Intentional Divergence

- Upstream exposes one CLI/workspace per host. harness-mem exposes one MCP
  lifecycle and keeps host details behind Adapters.
- Upstream Claude currently documents a note-first `knowledge-base.md` flow.
  harness-mem writes candidates into its governed memory store and uses
  `/hm:review`; it does not maintain a second knowledge-base truth source.
- Upstream contracts include host-specific `mark`, `bundle`, and raw-pruning
  commands. harness-mem does not expose these as the user lifecycle and never
  deletes native transcript evidence during distillation.
- Upstream hook-support flags describe its own adapter packages. harness-mem
  separately verifies its generated native hook/plugin integrations, so those
  flags are evidence inputs rather than harness-mem capability declarations.

## Aligned Source Variants

- Hermes supports both `~/.hermes/sessions/session_*.json` and the upstream
  `sessions/messages` SQLite schema in `state.db`. SQLite sessions are exported
  deterministically per session and covered by growth and project-isolation
  tests.
- Antigravity supports brain `transcript.jsonl` / `transcript_full.jsonl` plus
  the upstream `antigravity-cli/history.jsonl` conversation format. Shared
  history is exported per conversation so unrelated projects never enter the
  source revision.
- OpenCode storage and schema can change independently. Keep the upstream
  source-root contract as a watch signal, but require a local SQLite fixture and
  negative project match before changing the Adapter.

## Sync Rule

Future upstream updates may contribute parser lessons, source-root evidence,
lossless fixtures, final-review fields, and idempotency test vectors. They must
not directly replace harness-mem candidate governance, project identity, raw
retention, MCP contracts, or Dream behavior. All runtime behavior belongs under
`harness_mem/`; `tools/session-distill` contains only Agent instructions and
alignment references.
