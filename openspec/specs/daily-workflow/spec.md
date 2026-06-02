# daily-workflow Specification

## Purpose

定义 harness-mem 的日常用户可见工作流契约：`/hm:distill` / `/hm:wake` / `/hm:search` / `/hm:review` 与等价自然语言入口的 golden path。

把 v2.0/v2.1/v2.2 累积下来的"Slash + Skill + 自然语言为主入口、MCP 为隐藏传输层、CLI 仅做维护控制台"的承诺固化到一个 spec 里：项目解析顺序、distill 闭环、失败契约、auto-review 共享策略、证据强约束、kept_pending vs needs_user_confirmation 拆分、最终摘要 6 项 canonical counters、`/hm:review` 作为 repair-only 入口。

下游 v2.3-v2.7 的 signals、reflection、context assembly、wiki bridge、cross-project skill 工作必须沿用本 spec 的入口契约，不允许在不更新这里的情况下绕过 candidate-before-truth 或自动写 confirmed truth。
## Requirements
### Requirement: User-visible memory entrypoints

The system SHALL present daily memory workflows through IDE commands, Skills, or
natural-language agent instructions rather than terminal CLI command lists or raw
MCP tool names.

#### Scenario: Cursor user receives natural-language instruction

- **WHEN** a Cursor user asks how to wake project memory
- **THEN** documentation or agent guidance says "用 harness-mem 唤醒当前项目"
- **AND** it does not tell the user to run `harness-mem wake`

#### Scenario: Claude Code user receives slash command

- **WHEN** a Claude Code user wants to distill recent sessions
- **THEN** documentation points to `/hm:distill`
- **AND** the command instructions drive MCP tools behind the scenes

### Requirement: Project resolution before workflow execution

The agent SHALL resolve project context before running wake, search, distill, or
review workflows.

#### Scenario: Active project is available

- **GIVEN** the runtime has an active project
- **WHEN** the agent runs `/hm:wake` or equivalent
- **THEN** it uses the active project without asking the user to run CLI setup

#### Scenario: Project is ambiguous

- **GIVEN** active project and workspace root cannot determine one project
- **WHEN** the user requests a memory workflow
- **THEN** the agent asks one short clarifying project-name question

### Requirement: Distill closes the review loop

`/hm:distill` and natural-language equivalents SHALL complete the candidate loop
through evidence preparation, candidate writing, low-risk auto-review, and final
summary.

#### Scenario: Distill produces reviewed summary

- **WHEN** the user runs `/hm:distill`
- **THEN** the agent prepares an evidence packet
- **AND** writes candidates through `suggest_*`
- **AND** reviews pending candidates
- **AND** returns counts for ingested, candidates, auto-confirmed, auto-rejected, pending, and high-risk items

### Requirement: Auto-review uses one shared low-risk policy

Auto-review SHALL be implemented in a single shared module
(`harness_mem/commands/auto_review.py`) so `/hm:distill`, the
`session-distill` skill, and the MCP `auto_review_candidates` tool apply
identical noise rules, confidence floors, category lists, and evidence-id
checks across entrypoints.

#### Scenario: Slash, skill, and MCP share decision logic

- **GIVEN** a project has a pending candidate matching a noise pattern
- **WHEN** auto-review is run via `/hm:distill`, the `session-distill` skill,
  or the MCP `auto_review_candidates` tool
- **THEN** the candidate is auto-rejected in all three flows
- **AND** the rejection reason references the same noise category name across
  flows

### Requirement: Auto-confirm requires evidence ids

Auto-review SHALL only auto-confirm a candidate when it carries a concrete
evidence id. For `MemoryEntry` candidates evidence is `entry.source` with a
non-empty value other than `manual`. For `RuleCandidate` candidates evidence
is the first id in `examples`. Candidates that would otherwise auto-confirm
but lack evidence SHALL be deferred with a reason that names the missing
evidence.

#### Scenario: Manual-source memory entry defers instead of auto-confirming

- **GIVEN** a long, high-confidence `decision`-category memory entry whose
  `source` is `"manual"`
- **WHEN** auto-review runs on the project
- **THEN** the entry is deferred rather than auto-confirmed
- **AND** the decision reason states that auto-confirm requires an evidence id

#### Scenario: Rule candidate without examples defers instead of auto-confirming

- **GIVEN** a high-confidence rule candidate whose `examples` list is empty
- **WHEN** auto-review runs on the project
- **THEN** the rule candidate is deferred rather than auto-confirmed
- **AND** the decision reason states that auto-confirm requires examples

### Requirement: Final summary separates silent kept-pending from needs-user-confirmation

The auto-review summary SHALL separate "deferred but silent" candidates from
"deferred and needs your confirmation" candidates. Low-risk defers (e.g. a
`bug`-category memory entry that needs human triage) increment
`kept_pending` only. High-risk defers (rule candidates, or memory entries
that fell short of auto-confirm only because of missing evidence in the
`decision` / `architecture` categories) increment both `kept_pending` and
`needs_user_confirmation`.

#### Scenario: Low-risk bug defer is silent

- **GIVEN** a `bug`-category memory entry that exceeds the minimum content
  length but does not match auto-confirm
- **WHEN** auto-review runs on the project
- **THEN** the summary's `kept_pending` counter increments by one
- **AND** the summary's `needs_user_confirmation` counter does not increment

#### Scenario: Rule candidate defer surfaces to the user

- **GIVEN** a rule candidate whose confidence is below the auto-confirm floor
- **WHEN** auto-review runs on the project
- **THEN** the summary's `kept_pending` counter increments by one
- **AND** the summary's `needs_user_confirmation` counter also increments by one

### Requirement: Failure states are explicit

The workflow SHALL report MCP unavailable, no LLM agent, empty evidence packet,
project mismatch, and permission errors with user-readable messages and
developer diagnostic pointers.

#### Scenario: No LLM agent is available

- **WHEN** distill is requested without an available LLM agent
- **THEN** the workflow reports distill unavailable
- **AND** it does not fall back to heuristic extraction
- **AND** it points the developer at `tools/session-distill/SKILL.md` as the reference LLM-agent integration

#### Scenario: MCP transport is unavailable

- **WHEN** the agent attempts a daily memory workflow but MCP cannot be reached
- **THEN** the workflow reports "harness-mem MCP runtime unavailable"
- **AND** it does not silently fall back to terminal CLI commands as the daily path
- **AND** it points the developer at `harness-mem doctor` for diagnosis

#### Scenario: Evidence packet is empty

- **GIVEN** `prepare_session_distill` returns zero observations for the project
- **WHEN** the agent attempts to distill
- **THEN** the workflow reports "no recent session evidence for <project>"
- **AND** it does not invent candidates or call them "distilled"
- **AND** it suggests checking session source paths or running `harness-mem doctor`

#### Scenario: Project mismatch between request and runtime

- **GIVEN** the user-requested project name does not match the active project or workspace root
- **WHEN** the agent is about to run wake, search, distill, or review
- **THEN** the workflow reports the mismatch with both names visible to the user
- **AND** it asks one short clarifying question rather than silently choosing one

#### Scenario: Permission or filesystem error on data directory

- **WHEN** the workflow cannot read or write `~/.harness-mem/data/` or the project's source session files
- **THEN** the workflow reports "harness-mem cannot access <path>: <reason>"
- **AND** it does not retry destructively
- **AND** it points the developer at `harness-mem doctor` for the data-directory check

### Requirement: Final summary uses canonical counters

`/hm:distill` and equivalent natural-language flows SHALL emit a final summary
that uses the same six canonical counters so users and tests recognise the shape
across clients.

#### Scenario: Distill summary names six counters

- **WHEN** `/hm:distill` finishes a run
- **THEN** the user-visible summary names exactly these counters: `ingested` (新灌入), `candidates` (新候选), `auto_confirmed` (自动确认), `auto_rejected` (自动拒绝), `pending` (保留待定), and `high_risk` (需要你确认)
- **AND** `ingested` reports the session count returned by `ingest_sessions` / `prepare_session_distill`
- **AND** `candidates` reports the total `suggest_*` writes for this run
- **AND** `auto_confirmed` and `auto_rejected` report the applied auto-review actions returned by the `auto_review_candidates` summary (`auto_confirmed`, `auto_rejected`)
- **AND** `pending` reports the deferred candidates that auto-review kept silent and that do not require user attention this turn
- **AND** `high_risk` reports the deferred candidates surfaced as "需要你确认" because they would change long-term agent behaviour

#### Scenario: User asks why a candidate was confirmed or rejected

- **GIVEN** the summary lists auto-confirmed and auto-rejected counters
- **WHEN** the user asks why a specific item was confirmed or rejected
- **THEN** the agent can name the candidate id, the evidence id, and the policy reason from `auto_review_candidates.applied_decisions`

### Requirement: Review is a repair entry

`/hm:review` SHALL be positioned as a repair/recheck workflow, not as a required
step after every successful `/hm:distill`.

#### Scenario: Successful distill does not require review

- **WHEN** `/hm:distill` completes with low-risk candidates handled
- **THEN** the final summary does not instruct the user to run `/hm:review`
- **AND** high-risk leftovers are listed directly if any exist

#### Scenario: User explicitly invokes review for old pending leftovers

- **GIVEN** the project has pending candidates from earlier distill runs or user corrections
- **WHEN** the user explicitly runs `/hm:review` or asks the agent to "重新审核老的 pending 候选"
- **THEN** the agent resolves the project, lists pending candidates via MCP `list_candidates`, runs the same low-risk auto-review policy, and emits the canonical summary
- **AND** the workflow remains supported even though it is not part of the daily happy path

### Requirement: Session closure uses explicit maintenance guardrails

The system SHALL treat `/hm:mark <session-id> distilled [--keep-raw]` and its
natural-language equivalents as the formal user-facing entry for closing one
distilled session. A session SHALL NOT be marked `distilled` unless the
required session note, raw-review, promotion, draft, and knowledge-base
guardrails are satisfied.

#### Scenario: Distilled session passes all guardrails

- **GIVEN** a session has a completed note, reviewed raw transcript, explicit
  promotion decision, cleared memory draft state, and no unstable same-source
  knowledge-base entries
- **WHEN** the operator runs `/hm:mark <session-id> distilled`
- **THEN** the session is marked `distilled`
- **AND** the response names any follow-up reminder without requiring a
  separate review workflow

#### Scenario: Missing guardrail blocks closure

- **GIVEN** one required note or draft guardrail is still missing
- **WHEN** the operator tries to mark the session `distilled`
- **THEN** the session is not marked `distilled`
- **AND** the response identifies the missing guardrail

### Requirement: Manifest cleanup is confined to handled placeholders

The system SHALL treat `/hm:prune --statuses distilled,skipped --source-missing`
and its natural-language equivalents as cleanup for handled manifest
placeholders only.

#### Scenario: Cleanup removes source-missing handled placeholder only

- **GIVEN** a manifest row is already `distilled` or `skipped`
- **AND** its raw source is missing
- **WHEN** the operator runs `/hm:prune --statuses distilled,skipped --source-missing`
- **THEN** the handled placeholder may be cleaned up
- **AND** no confirmed rule, accepted memory entry, relation fact, shared skill,
  or unrelated raw transcript is mutated

#### Scenario: Cleanup does not remove active unresolved work

- **GIVEN** a manifest row is still unresolved or its source still exists
- **WHEN** the operator runs the prune flow
- **THEN** that row is not cleaned up merely because prune ran

### Requirement: Raw deletion stays inside explicit mark flow

Raw transcript deletion SHALL only occur as part of the explicit mark flow and
shall remain opt-out via `--keep-raw`.

#### Scenario: Keep-raw bypass preserves transcript

- **GIVEN** a session otherwise satisfies closure guardrails
- **WHEN** the operator runs `/hm:mark <session-id> distilled --keep-raw`
- **THEN** the session may still be marked `distilled`
- **AND** the raw transcript is preserved

### Requirement: Knowledge-base review is an explicit maintenance audit

The system SHALL treat `/hm:review-kb --next <n>` and its natural-language
equivalents as the formal user-facing audit entry for the session-distill
knowledge base.

#### Scenario: Review classifies entries and records baseline

- **WHEN** the operator runs `/hm:review-kb --next 20`
- **THEN** the system classifies knowledge entries into `stable`,
  `needs-review`, `stale`, or `superseded`
- **AND** it records the review timestamp, total entry count, and per-status
  summary for future reminder decisions

### Requirement: Knowledge-base prune is backup-first and status-confined

The system SHALL treat `/hm:prune-kb --statuses stale,superseded` and its
natural-language equivalents as explicit cleanup for stale/superseded
knowledge-base entries only.

#### Scenario: Prune writes backup before mutating knowledge base

- **GIVEN** at least one knowledge entry is classified as `stale` or `superseded`
- **WHEN** the operator runs `/hm:prune-kb --statuses stale,superseded`
- **THEN** the system writes a backup copy before cleanup
- **AND** it removes only the matching stale/superseded knowledge entries

#### Scenario: Prune does not mutate canonical truth

- **WHEN** knowledge-base prune runs
- **THEN** it does not confirm, reject, supersede, retire, or delete canonical
  rule/memory/fact/skill truth as a side effect

### Requirement: Targeted verification is an explicit maintenance entry

The system SHALL treat `/hm:verify-entry <session-id|keyword>` and its
natural-language equivalents as the formal user-facing entry for targeted
knowledge-base recheck.

#### Scenario: Verify-entry returns matching entries and recheck questions

- **WHEN** the operator runs `/hm:verify-entry <session-id|keyword>`
- **THEN** the system returns matching knowledge entries
- **AND** it includes grill-style recheck questions for each match

### Requirement: Maintenance reminders are summary-only nudges

Review and overlap reminders SHALL stay advisory and SHALL NOT silently mutate
knowledge or confirmed truth.

#### Scenario: Review-baseline reminder after knowledge growth

- **GIVEN** the knowledge base has grown beyond the configured reminder threshold
- **WHEN** a session is marked `distilled`
- **THEN** the summary may suggest `/hm:review-kb --next <n>`
- **AND** the mark flow still completes if all closure guardrails passed

#### Scenario: Overlap reminder after packet or note creation

- **GIVEN** a new packet or session note overlaps earlier knowledge entries
- **WHEN** the maintenance summary is rendered
- **THEN** the summary may suggest `/hm:verify-entry <keyword>`
- **AND** it does not auto-prune, auto-supersede, or block distill completion
