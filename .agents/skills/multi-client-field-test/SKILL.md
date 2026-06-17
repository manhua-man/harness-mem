---
name: multi-client-field-test
description: |
  Generate a multi-client field-test packet for a release: one realistic
  persona per target client, each with reading whitelist, role-play
  discipline, and a step-by-step flow that exercises the release's specific
  promises. Use when the user asks "we need to test this in production-like
  conditions", "发版前怎么验", "给我编几个真实用户测试 v2", "我们要测三个
  客户端 / 三个平台", or any phrasing that asks for cross-client / cross-
  surface user validation packets — not unit tests, not benchmarks.
license: MIT
metadata:
  author: harness-mem
  version: "1.0"
---

# Multi-Client Field Test Packet

You are building **scripts for the developer to role-play as real users
across multiple clients of the same product**. The output is not a test
suite. It's a packet of personas the developer takes through the product
themselves, in each target client, while pretending not to be a developer.

This skill exists because:

- **Unit tests** prove functions return correct values.
- **Loop harnesses** prove multi-step processes hold together internally.
- **Field tests** prove that **a real user, in a specific client, with the
  documents they're allowed to read, can actually use the product** — and
  that the release's headline promises survive contact with someone who
  isn't already on the team.

When a project ships across multiple clients (e.g. Codex + Codex CLI
+ Cursor; or web + iOS + Android; or VS Code extension + Vim plugin + CLI),
each client has different conventions, integration points, and prompt
ergonomics. Promises like "any LLM agent can drive this" or "works
identically across platforms" are usually false in subtle ways. This skill
forces those subtleties into view before users find them.

---

## When this is the right tool

Use when **all** of these hold:

- The release has a headline promise that involves multiple clients,
  surfaces, or platforms ("MCP-first", "any LLM agent", "cross-platform")
- The team is small enough that they're the only "users" so far
  (dogfooding ≠ external validation)
- The release is about to ship or just shipped, and "did we deliver on the
  promise" is an open question
- A single benchmark / loop harness can't measure it, because the friction
  is in setup, prompt ergonomics, and which docs the user reads

Do **not** use when:

- The product has a single client. Use one persona, not a packet.
- The release is purely backend / infra (no user-visible surface change).
- You can run the test yourself in code. Then write a test, not a packet.

If unsure, ask: "Are we testing the implementation or the experience?"

---

## Design Principles

### 1. One persona per client, not one persona per use case

The whole point is that **the client matters**. Same use case, three
clients, three personas. If two personas would have the same role-card
fields except for client name, you're doing it wrong — you've got one
persona that uses three clients, which doesn't surface the client-specific
friction.

Each persona must have a **reason they prefer this client**, not just a
client assignment.

### 2. Reading whitelist is the audit core

Every persona has an explicit "你被允许读的文档" section. This is the
**single most important element** of the skill. Without it:

- The developer role-playing the persona will subconsciously read source
  to fill gaps
- The packet ends up testing "can the developer who built this make it
  work" instead of "can a real user with public docs make it work"
- The friction that actually kills adoption (missing docs, broken
  examples, undocumented MCP setup) becomes invisible

Different personas should get different whitelists. The most stringent
whitelist (typically the last persona, the one who is *least* invested
in the project) is where you find the real failures.

### 3. Personas vary in investment, not just in client

A common mistake is making all three personas "engineers who want to try
the tool". Real client populations differ in:

- **Investment**: power user dogfooder ↔ casual try-it-out user
- **Existing pain**: "this is my daily blocker" ↔ "this might be useful"
- **Tolerance for setup**: "I'll read AGENTS.md if I have to" ↔ "if pip
  install doesn't work I'm out"
- **Project depth**: "6万 LOC main project" ↔ "exploring an idea"

The packet should span this range, not cluster at one end. The headline
promise needs to survive the casual-try-it-out user, not just the
dogfooder.

### 4. Steps must hit version-specific promises

Each persona's step-by-step flow has to exercise **the release's specific
delta**, not just generic functionality. If v2.0 removed heuristic distill
and promised "any LLM agent drives distill via MCP", the steps must
include "trigger distill from this client" and "observe whether the agent
actually drives it via MCP or hallucinates a CLI command".

A persona flow that would have looked the same in v1.x is not exercising
v2.0.

### 5. Triage matrix at the end, not a "fix list"

The packet's job is to surface friction, not fix it. The triage matrix
classifies each blocker as:

- **Real bug** (all personas hit it) → P0 patch
- **Client-specific** (one client / one persona) → docs / prompt fix
- **Persona-specific** (one role's edge case) → roadmap, not blocker
- **README/承诺 mismatch** (docs claim X, reality is Y) → P0 docs

Without this matrix, the developer ends up with a list of complaints and
no decision rule for what to do next.

---

## Process

### 1. Identify the clients to cover

List the target clients explicitly. For each, name **why** it matters
for this release. Example for harness-mem v2.0:

- Codex: dogfood baseline, slash commands assumed
- Codex CLI: tests "decoupled from Codex" promise
- Cursor: tests "any MCP client works" promise (least invested users)

If a client isn't in the release's promise, skip it. Don't pad to 3.

### 2. Build one persona per client

Each persona uses the role-card format from `project-honest-audit`
(name, age, location, working style, specific stack, primary pain,
competitors tried). Add **client-specific layer**:

- Why they chose this client over alternatives
- What their workflow inside this client looks like
- Which integration mechanism they'd actually find (slash? MCP config?
  CLI?)

Investment should differ across personas. The least-invested persona is
typically assigned the client whose support is most aspirational in the
release. That's where the headline promise gets stress-tested.

### 3. Write the reading whitelist per persona

For each persona, list the **exact** documents they're allowed to read.
Be ruthless. Default to:

- README (sometimes only specific sections)
- The output of installation / quickstart commands
- What the agent shows them inside the client

Default to **excluding**:

- Source code
- AGENTS.md / contributor docs (unless persona is a contributor)
- SKILL.md or other internal prompts
- CHANGELOG (unless explicitly part of the experience)

Less invested personas get smaller whitelists. The dogfooder might be
allowed to read more.

### 4. Write step-by-step flows that exercise the release delta

Each persona gets 5-6 steps. Each step must:

- Be a thing the developer can literally type / click while role-playing
- End with "记录: ..." prompts that ask for specific observable signals
- Include at least one step that exercises a **release-specific promise**
- Include at least one **unhappy path** (something breaks, what's the UX?)

Steps should escalate: setup → first happy path → core promise validation
→ schema migration / supersede / correction → cross-feature interaction →
honest ROI question.

### 5. Add release-specific focus points per persona

After the steps, list "v<X>.<Y> 关注点" for that persona — what aspects
of the release this specific persona is best positioned to surface.
Different personas catch different things.

If two personas have identical focus points, you've over-cloned them.

### 6. End with role-play discipline + triage matrix

The packet must include:

- **Common role-play discipline** at top (forget you're a developer; only
  read whitelist; record errors verbatim; use a real project not empty
  repo)
- **Per-persona feedback table template**
- **Triage matrix** (4 categories above)

Without these scaffolds, the developer testing it will drift back into
developer mode mid-flow.

---

## Output Layout

Single markdown file at `docs/v<X>-user-test-packet.md` (or
`docs/<release-name>-field-test-packet.md`).

```markdown
# <product> v<X> 用户测试 Packet

> Brief framing: this is role-play scripts, not marketing personas.

## 共用扮演纪律
[5-6 rules: forget you're a dev, only whitelist docs, record verbatim,
real project not empty repo, etc.]

## Persona A: <name> (<client>, <投入度 framing>)
### 角色卡
### 你被允许读的文档
### 环境准备
### 执行步骤
- Step 1 ... 记录: ...
- Step 2 ... 记录: ...
- Step 3 (核心 promise validation) ... 记录: ...
- Step 4 (unhappy path / supersede) ... 记录: ...
- Step 5 ...
- Step 6 (心算 ROI) ... 记录: ...
### v<X> 关注点

## Persona B: ...

## Persona C: ...

## 反馈表模板
[Per-persona table the dev fills in after the run]

## 三个 persona 跑完之后
[Triage matrix: 真问题 / 客户端特定 / persona-specific / README 承诺脱节]
```

---

## Anti-patterns to refuse

- **Don't run the personas yourself.** The whole value is the developer
  role-playing them in a real client. If you simulate, you're cheating
  away the entire reason for the skill. State this explicitly when
  delivering the packet.
- **Don't make all personas similarly invested.** If they're all "eager
  early adopters", you'll never find the casual-user friction.
- **Don't omit reading whitelists.** A persona without a whitelist is
  just a marketing demographic.
- **Don't write generic steps that work in any version.** Each persona's
  flow must exercise the specific release delta.
- **Don't propose fixes inside the packet.** That's after the test runs.
  The packet's job is to surface friction, not preempt it.
- **Don't merge personas to fit a template count.** If only 2 clients
  matter, ship 2 personas. If 4 matter, ship 4.
- **Don't skip the triage matrix.** Without classification, the feedback
  becomes a wishlist with no priority.

---

## Related Reality-Check Skills

This skill is one of three sharing the same evidence-over-narrative
discipline:

| Skill | When to use | Output |
|---|---|---|
| `project-honest-audit` | "How is this project doing overall?" — find risks before transition | Markdown audit report with scorecard |
| `loop-evaluation-harness` | "Is our multi-step loop actually working end-to-end?" — instrument the loop | `tests/loop_harness/` test code + README |
| `multi-client-field-test` (this skill) | "Will real users in each target client succeed?" — pre-release validation | Markdown persona packet at `docs/...-packet.md` |

Common patterns escalate naturally:

- An audit identifies "we promise cross-client support but only test in
  Codex" → use `multi-client-field-test` to build the validation
- A loop harness shows the wiring works but you can't tell if the UX
  feels usable → use `multi-client-field-test` to add experiential signal
- A field test reveals "the loop seems broken in Cursor" → use
  `loop-evaluation-harness` to add a deterministic scenario for it

---

## When NOT to use this skill

- Single-client product. One persona is fine; this skill's overhead doesn't
  pay off.
- Release with no user-visible promise change. If nothing externally
  observable changed, there's nothing for personas to test.
- The team has external users actively giving feedback. Real users beat
  role-played personas. Use this when you don't have that signal yet.
- Pre-MVP / < 500 LOC / < 1 month. The product isn't stable enough to
  test against personas usefully.

If unsure, ask: "Do we have external users we can ask, or are we still
the only ones using this?"
