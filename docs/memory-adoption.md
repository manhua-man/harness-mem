# Memory Adoption: Optional Helpers Beside harness-mem

Operator policy for optional helpers. This page does not add another runtime or
MCP surface; the task-aware runtime scheduler lives in
`autopilot_search_tick` and [autopilot-search-policy.md](autopilot-search-policy.md).
`grill-before-distill` (grill-me) is the **standard admission mode** on distill
— automatic, depth by risk (not a forced heavy loop every time). Other helpers
stay opt-in.

## Conclusion

| Helper | Verdict |
|---|---|
| **smart-search** | Reference project for future evidence-backed knowledge review; not adopted yet |
| **grill-me / grill-before-distill** | Standard admission; depth by risk |
| **Trellis** | Borrow patterns only; do not embed in harness-mem |

## Introduction rules

| Rule | Meaning |
|---|---|
| MCP = tools | Memory surface stays hm MCP |
| Workflow = Skills | grill-before-distill now; smart-search and Trellis remain reference/optional layers |
| grill-me standard admission | Auto on distill; deep vs light vs lookback by risk |
| Other helpers opt-in | smart-search / Trellis: reference only unless a project explicitly enables them |
| One truth layer | confirmed memory + ledger; **no** Trellis journal dual-write |

## Layer map

| Layer | Job | Use |
|---|---|---|
| Requirement interrogation | Clarify fuzzy intent | **grill-before-distill** (Skill) |
| Task / PRD / delivery | Structured delivery artifacts | **Trellis** (optional, project-level) |
| Local auditable memory | Candidate → review → truth | **harness-mem** (core) |
| External fact checking | Docs, policy, vendor sites | smart-search-style CLI evidence support (future candidate) |
| In-repo fact checking | Code, sessions, memory | **search_memory** |
| Code acceptance | lint / test / regression | pytest / ruff (**not** memory layer) |

**Architecture accident:** Trellis `journal` + harness-mem `confirmed memory` as
two truth sources.

## Default harness-mem chain

```text
模糊结论 / session-end
  → hook 保存不可变 transcript source revision，并排队全部有序 chunks（不做摘要）
  → prepare_session_distill → 完整读取 chunk，不截断；逐 chunk checkpoint
  → 全部 expected chunks 完成且 source revision 未变化
  → 必须执行 final-session review
  → grill-me 准入（高风险深度 / 普通轻量 checklist）
  → admit/narrow 才幂等 suggest_* → pending；defer/reject 不写
  → 内部 search_memory；外部证据工具（smart-search 为参考候选，confirm 前必须补证）
  → finalize_session_distill → auto-review + Dream
  → auto_confirmed / provisional truth
  → /hm:review audit/undo → user_confirmed

已确认记忆回看 / dream → grill-me lookback（防过时、防误导）
```

Automatic; depth scales by risk — not a heavy re-flow every time.

The immutable source revision, not an Observation or derived evidence bundle,
is authoritative for session text. Its ordered chunks must reconstruct the
complete revision. Per-chunk checkpoints make retries resumable, and
idempotent candidate keys prevent duplicate promotion.

## Optional helpers on the chain

```text
distill 完整处理有序 chunks → per-chunk checkpoints → final-session review
  → 幂等候选
  → 外部事实? evidence search/fetch support + source
  → 代码事实? search_memory
  → finalize_session_distill 自动执行 auto-review + Dream
  → /hm:review 事后审计；confirm_* 写入 user-confirmed 真相
```

Evidence does not have to block candidate creation. It does block confirmation:
external or version-sensitive claims must carry a fetched/source-backed evidence
bundle before `confirm_*`. smart-search is a reference candidate for that role;
it is not a current harness-mem dependency or installed skill.

Skill: `plugins/harness-mem/skills/grill-before-distill/SKILL.md`

Admission actions stay on the main write path:

| Action | Continue how |
|---|---|
| `admit` | Continue to `suggest_*`. |
| `narrow` | Rewrite scope/wording, then continue to `suggest_*`. |
| `defer` | Keep as pending/note or evidence gap; do not write candidate yet. |
| `reject` | Drop as noise/local-only/misleading. |

Dream is not the admission target. Dream/lookback is for already confirmed or
maintained memory and may later propose keep/narrow/supersede/reject decisions
through its ledger and undo path.

Question routing:

| Grill question | First answer source | Escalation |
|---|---|---|
| Evidence or source proof | immutable source revision/chunks, `search_memory`, files/tests/docs | `answer-memory-evidence` |
| Kind, scope, freshness, misleading risk | Agent reasoning over complete chunks + repo context | grill deeper or defer |
| Architecture, product boundary, roadmap, long-lived default | existing docs and code ownership | `ask-memory-boundary` |
| User preference or durable intent | user statements | ask user only when evidence cannot decide |

## smart-search reference project

Status: reference only. A local workspace mirror can live under
`.tmp/reference-projects/smartsearch`; that path is ignored by git and is not
part of the product surface.

- Models guess; they do not cite.
- External claims in candidates (API, version, policy, papers) need sources.
- Knowledge-base / confirmed-memory management also needs search support when
  old entries are audited for freshness, supersession, or misleading scope.
- Use `search` / `fetch` / `research` + `evidence_policy="fetch_before_claim"`.
- If adopted later, keep it as CLI/Skill evidence support, not hm MCP and not a
  truth writer.
- Requires provider keys; not a runtime dependency.
- Context7 / mcp-deepwiki-style retrieval can be studied through this CLI
  pattern instead of adding more default MCP.

## Evidence policy (P0 operator recommendation)

| Claim type | Cite via |
|---|---|
| Session statements | Immutable source revision and its complete ordered chunks |
| Repo / code / prior memory | Current files/tests/docs plus `search_memory`; derived Observations are discovery aids only |
| External / version-sensitive | fetched/source-backed evidence; smart-search is a reference candidate |
| High blast-radius rules | grill-before-distill + human before confirm |
| Stale confirmed truth | dream / audit + re-check |

Not runtime-enforced until a future explicit gate cites this doc.

## Trellis: patterns only

| Trellis | harness-mem | Recommendation |
|---|---|---|
| trellis-check | `auto_review_candidates` (memory only) | Code check separate; memory stays hm |
| update-spec | `govern_memory(action="decide", kind="rule")` + promote to AGENTS.md | Adopt pattern; no `.trellis/spec/` in hm |
| finish-work | `create_task_handoff` + dream hook | Map only |
| journal | event_log + confirmed memory | hm wins; no dual journal |

**Hard boundary:**

- Trellis: `.trellis/tasks/`, `prd.md`, `implement.jsonl` (project-level)
- harness-mem: candidates, confirmed truth, wake/search

Do not embed Trellis in harness-mem repo (AGPL, dual harness, path conflicts).

### Trellis Pattern Playbook

This is the executable borrowing layer. It maps Trellis habits to existing
`harness-mem` surfaces without installing Trellis or creating a second truth
store.

| Pattern | Operator action in harness-mem | Never do |
|---|---|---|
| `check` | Run code acceptance with the project test stack (`pytest`, `ruff`, app-specific checks). Run memory acceptance with `auto_review_candidates(apply=true)` for low-risk automation, then use `/hm:review` for audit, undo, and high-risk decisions. | Do not treat `auto_review_candidates` as code validation; do not treat passing tests as memory confirmation. |
| `update-spec` | When a repeated lesson should change future behavior, use `govern_memory(action="suggest")`; after confirmation, update repo guidance such as `AGENTS.md` only when the scope is repo-wide. | Do not create `.trellis/spec/` or a parallel PRD truth layer inside hm. |
| `finish-work` | At task/session end, call `create_task_handoff` for current state, blockers, and next steps. Then read or trigger `/hm:dream` only when maintenance or ledger review is needed. | Do not double-write task state to a Trellis journal and hm handoff. |
| `journal` | Use `event_log` / state audit for governance history, `timeline` / `search_memory` for retrievable memory history, `create_task_handoff` for task continuity, and `dream_ledger` for maintenance history. | Do not install or sync Trellis journal as durable project memory. |

Closeout checklist:

```text
1. Code check: run the repo's tests/lint/build for the changed surface.
2. Memory check: run low-risk auto-review for new candidates; audit high-risk or surprising outcomes through hm review tools.
3. Update-spec equivalent: promote repeated lessons to rule/doc candidates, not Trellis specs.
4. Finish-work equivalent: create task handoff and inspect dream ledger when useful.
5. Journal equivalent: rely on hm audit/event/timeline/handoff surfaces, not a second journal.
```

## 11-step personal flow → harness-mem

| Step | harness-mem side |
|---|---|
| grill-me admission | Standard mode before writes; lookback on confirmed truth |
| ACE / code | `search_memory` + `get_observations` |
| smart-search | Reference evidence provider for future KB/review support; not hm core |
| Trellis PRD/design/implement | Project optional; not hm core |
| Agent execution | wake → search → implement |
| MCP on demand | Browser/GitHub/etc.; memory via hm MCP |
| trellis-check | pytest/ruff; separate from auto_review |
| update-spec | `govern_memory(action="decide", kind="rule")` + repo rules |
| finish-work / journal | `create_task_handoff` + dream; journal = confirmed memory |

## Adoption priority (KISS)

| Priority | Action | Hard-wire? |
|---|---|---|
| **P0** | `grill-before-distill` — default distill step | Skill layer yes; MCP no |
| **P0** | Evidence policy (this doc) | No |
| **P1** | Study smart-search as a reference evidence provider for knowledge review | No |
| **P2** | Project-level Trellis init if team wants PRD pipeline | No |
| **Don't** | Trellis check/finish/journal in hm runtime | — |

## One line

smart-search = reference evidence provider for future knowledge review support;
grill-before-distill = admission before writes; Trellis = optional task
orchestration — not something harness-mem should swallow.

## References

- [smart-search](https://github.com/konbakuyomu/smartsearch)
- [Trellis](https://github.com/mindfold-ai/Trellis)
