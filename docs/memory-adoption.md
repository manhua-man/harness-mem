# Memory Adoption: Optional Helpers Beside harness-mem

Operator policy only. **No runtime or MCP changes.** `grill-before-distill`
(grill-me) is the **standard admission mode** on distill — automatic, depth by
risk (not a forced heavy loop every time). Other helpers stay opt-in.

## Conclusion

| Helper | Verdict |
|---|---|
| **smart-search** | Reference project for future evidence-backed knowledge review; not adopted yet |
| **grill-me / grill-before-distill** | Standard admission; depth by risk |

## Introduction rules

| Rule | Meaning |
|---|---|
| MCP = tools | Memory surface stays hm MCP |
| Workflow = Skills | grill-before-distill now; helper choice stays explicit and opt-in |
| grill-me standard admission | Auto on distill; deep vs light vs lookback by risk |
| Other helpers opt-in | smart-search: reference only unless a project explicitly enables it |
| One truth layer | confirmed memory + ledger |

## Layer map

| Layer | Job | Use |
|---|---|---|
| Requirement interrogation | Clarify fuzzy intent | **grill-before-distill** (Skill) |
| Local auditable memory | Candidate → review → truth | **harness-mem** (core) |
| External fact checking | Docs, policy, vendor sites | smart-search-style CLI evidence support (future candidate) |
| In-repo fact checking | Code, sessions, memory | **search_memory** |

**Architecture guardrail:** confirmed memory + ledger are the only durable
memory sources.

## Default harness-mem chain

```text
模糊结论 / session-end
  → prepare_session_distill → session-distill drafts candidate claims
  → grill-me 准入（高风险深度 / 普通轻量 checklist）
  → admit/narrow 才 suggest_* → pending；defer/reject 不写
  → 内部 search_memory；外部证据工具（smart-search 为参考候选，confirm 前必须补证）
  → auto_review (preview) → /hm:review → confirm_* → confirmed truth

已确认记忆回看 / dream → grill-me lookback（防过时、防误导）
```

Automatic; depth scales by risk — not a heavy re-flow every time.

## Optional helpers on the chain

```text
distill 产出候选
  → 外部事实? evidence search/fetch support + source
  → 代码事实? search_memory
  → auto_review 或 /hm:review
  → confirm_* 写入真相
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
| Evidence or source proof | packet, observations, `search_memory`, files/tests/docs | `answer-memory-evidence` |
| Kind, scope, freshness, misleading risk | Agent reasoning over packet + repo context | grill deeper or defer |
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
| Repo / code / prior memory | `search_memory`, `get_observations`, file reads |
| External / version-sensitive | fetched/source-backed evidence; smart-search is a reference candidate |
| High blast-radius rules | grill-before-distill + human before confirm |
| Stale confirmed truth | dream / audit + re-check |

Not runtime-enforced until a future explicit gate cites this doc.

## One line

smart-search = reference evidence provider for future knowledge review support;
grill-before-distill = admission before writes.

## References

- [smart-search](https://github.com/konbakuyomu/smartsearch)
