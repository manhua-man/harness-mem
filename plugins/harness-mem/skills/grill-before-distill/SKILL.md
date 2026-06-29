---
name: grill-before-distill
description: |
  Standard memory admission mode for harness-mem (grill-me role). Runs
  automatically on distill — depth scales by risk, not a forced heavy loop every
  time. Three modes: deep interrogation, light checklist, lookback for stale
  truth. No writes. More than a review-stage helper: admission plus lookback.
allowed-tools:
  - Read
  - Grep
---

# grill-before-distill (grill-me 准入)

## What this is

**标准准入模式** — not a mandatory heavy re-interrogation on every distill.
It is a question router plus pressure-test verdict for the main memory chain.

Complements `tools/session-distill/references/distillation-rules.md`; does not
replace `/hm:review`.

| Phase | Job |
|---|---|
| grill-me / grill-before-distill | Admission (depth by risk) |
| session-distill | Extract candidates |
| /hm:review + confirm_* | Durable confirmation |

Runs automatically when distill or memory write is in play — user does not say
「先拷问」. Pick the **lightest sufficient mode**; escalate when risk rises.

`admit` / `narrow` / `defer` / `reject` are main-chain actions, not dream
actions:

| Action | Main-chain meaning |
|---|---|
| `admit` | Candidate is allowed to continue to `suggest_*`. |
| `narrow` | Candidate is useful but wording/scope must be narrowed before `suggest_*`. |
| `defer` | Do not write yet; keep as pending/note and attach the missing evidence or question. |
| `reject` | Do not write a candidate; treat as noise, local-only, duplicate, or misleading. |

Dream is different: dream/lookback handles already confirmed or maintained
truth and may suggest `keep`, `narrow`, `supersede`, or `reject` for later
review/undo. Admission actions only decide whether the write path continues.

## Three modes (pick by risk)

### Mode A — Deep grill-style interrogation (必须)

**When:**

- User explicit rule: 「记住」「以后都这样」「写成项目规则」
- `suggest_rule` or repo-wide AI behavior change
- High blast-radius: architecture fact, security, release policy, cross-team default
- Ambiguous fuzzy conclusion on a draft claim after packet read (not before `prepare_session_distill`)

**How:** route one unresolved question at a time until the action is clear (see
checklist below). Answer from evidence first; ask the user only when evidence
and local context cannot decide.

### Mode B — Light checklist pass (默认)

**When:**

- Ordinary `/hm:distill` / session-distill candidates
- Low–medium risk `suggest_memory_entry`, handoff, relation with clear evidence
- Packet-backed facts with observation ids already attached

**How:** run the 5-point checklist **inline in one pass** (no multi-turn loop
unless an item fails). Tag `risk: low`; `admit` if all pass.

```text
[ ] reusable beyond this session?
[ ] kind + scope clear?
[ ] evidence id / path present?
[ ] not session noise (distillation-rules reject list)?
[ ] wording not overbroad?
```

Fail any → route the unresolved question, then either `narrow`, escalate to
Mode A for that item only, `defer`, or `reject`.

### Mode C — Lookback (已确认记忆回看，grill-me 主力)

**When:**

- Dream maintenance, `/hm:review` spot-check, wake surfaced stale truth
- User asks「这条还对吗」「会不会误导」
- Supersede / conflict signals on confirmed memory

**How:** adversarial lookback — failure modes, expiry, misleading scope, missing
supersede. May use `search_memory` and, in future, a source-backed external
evidence tool such as smart-search to re-verify. Output:
`keep` / `narrow` / `supersede` / `reject` for the maintenance/review path
(no silent truth overwrite).

## Default routing

| Situation | Mode |
|---|---|
| `/hm:distill` bulk candidates | **B** per item; **A** if rule/high-impact |
| User「记住这个」| **A** |
| Autopilot boundary suggest | **B**; **A** if rule candidate |
| Confirmed memory audit | **C** |
| Pure code work, no memory intent | skip |

## Question routing

`grill-before-distill` asks the question and routes it to the right answer
source. It does not default to asking the user.

| Question type | First answer source | Escalate to |
|---|---|---|
| Evidence: "what proves this?" | packet, observation id, `search_memory`, files, tests, docs | `answer-memory-evidence` |
| Scope/kind: "fact, rule, handoff, relation, or local note?" | packet + distillation-rules | user only if intent is ambiguous |
| Freshness: "could this be stale?" | current repo files, tests, docs, timeline/search | external source-backed evidence in future |
| Misleading risk: "would future Agents over-apply this?" | grill-style self-critique | `ask-memory-boundary` if product/architecture boundary matters |
| Architecture/product boundary | existing docs, roadmap, code ownership | `ask-memory-boundary` |
| User preference or policy intent | user-stated instruction | ask user |

Answer before asking. Ask the user only when the missing information is a
preference, intent, or product decision that evidence cannot settle.

## Checklist (Mode A — one unresolved question per turn)

| Order | Question | If no → |
|---|---|---|
| 1 | Reusable? | `defer` to note / `reject` |
| 2 | Kind? | keep asking |
| 3 | Scope? | keep asking |
| 4 | Evidence plan? | route to evidence lookup |
| 5 | Expiry? | tag risk |

**Main-chain action:** `admit` | `narrow` | `defer` | `reject`

Admission note (no MCP writes):

```text
mode: deep | light | lookback
action: admit | narrow | defer | reject
kind + scope: (if admit/narrow)
routing: agent | answer-memory-evidence | ask-memory-boundary | user
evidence_plan: internal | external | both | none
risk: low | medium | high
```

## Main chain position

```text
模糊结论 / session-end
  -> prepare_session_distill
  -> 读 packet + draft candidate claims
  -> grill-me 准入（A/B 按风险；对 draft claim，不是空会话先拷问）
  -> suggest_*（admit；narrow 后可写；defer/reject 不写）
  -> 内部 search_memory / 代码检索；外部来源证据（smart-search 为参考候选）
  -> auto_review preview + /hm:review
  -> confirm_* -> confirmed truth

已确认记忆维护 / dream / 抽查 -> Mode C lookback
```

## Boundaries

| Does | Does not |
|---|---|
| Scale admission depth by risk | Force heavy loop on every candidate |
| Run automatically on distill path | Write candidates or confirmed truth |
| Mode C for stale truth | Replace `/hm:review` gate |

## Non-goals

- Not only compare-bundle review-stage pressure testing; primary role is admission plus lookback
- Not a second truth source
- Not a new MCP tool

## References

- `docs/memory-adoption.md`
- `tools/session-distill/references/distillation-rules.md`
- `tools/session-distill/SKILL.md`
