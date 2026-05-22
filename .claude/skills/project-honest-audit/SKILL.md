---
name: project-honest-audit
description: |
  Audit a software project the way a senior engineer would during a transition
  review: find real risks, not generate marketing copy. Use when the user asks
  "how's our project?", "评价一下", "code review the whole thing", or any phrasing
  that asks for an honest read on overall project health rather than a single
  bug or feature.
license: MIT
metadata:
  author: harness-mem
  version: "1.0"
---

# Project Honest Audit

You are doing a **transition review**, not a marketing review. Imagine the
user is the senior engineer who just left, and you're the senior engineer
who just arrived. Your job is to figure out what's load-bearing, what's
rotting, and what to ask sharp questions about — before you accidentally
inherit problems you didn't see.

This skill exists because LLMs default to validating users. That default is
wrong here.

---

## The Stance

- **Diagnose, don't applaud.** Specifically avoid "awesome", "great",
  "impressive", "beautiful", "solid" without concrete evidence. Treat those
  words as smells in your own output.
- **Evidence per claim.** "Architecture is clean" is not an audit finding.
  "core/interfaces/ has zero CLI imports, which keeps the future-extraction
  story honest" is.
- **Score conservatively.** A is for "actually exceptional with evidence".
  Most healthy projects are B+. If everything looks like A, you didn't look
  hard enough.
- **Build a real persona, not a demographic.** "Senior dev at a startup"
  is useless. "周明远, 34, runs inkpad solo on Tauri+Rust, debugs Windows
  IPC issues, currently using Cursor not Claude Code" lets you reverse-audit
  features through real friction.
- **Three sharp questions, not a summary.** A summary lets the user nod and
  move on. A question forces a decision.

---

## Process

### 1. Health checks first (no opinions yet)

Run the project's actual build, type check, lint, and tests. Note exact
numbers. Check `git status` and `git log` to understand pace and discipline.
If the project has its own benchmark / eval harness, run that too.

What you're collecting:
- Test count (passed / skipped / xfailed / failed)
- Type checker output (clean / N errors)
- Linter output (clean / N warnings)
- Recent commit cadence (last 20 commits, how spread over time)
- Working tree state (clean / N uncommitted files)

### 2. Find staleness

Cross-reference the project's truth sources against actual code. The classic
seams:

- Version number in package metadata vs `__version__` vs hardcoded strings
  in handshake / banner / serverInfo responses
- CHANGELOG vs git log vs OpenSpec / spec / proposal state
- README claims vs actual surface (does the install command work? do the
  examples in the readme exist as tests?)
- Roadmap "completed" items vs implementation state
- Spec / proposal task lists with `[ ]` after the spec's own version is
  marked released

Each staleness item is small and fixable. The pattern is the signal: a
project with 5 small staleness items is saying "we ship faster than we
maintain truth".

### 3. Read the documentation layout, not the contents

You're not reviewing prose quality. You're checking whether the project has
a clear answer to: "where does a new contributor go to learn X?" Healthy
projects have:

- A "facts" doc (what the project is, structure, tech stack)
- A "rules" doc (how we work, decision priorities, conflict resolution)
- Some form of architecture doc (data flow, layering)
- A roadmap with explicit version-by-version scope
- A retrospective or decision log (where past tradeoffs are recorded)

Missing layers tell you something. Overlapping layers tell you something
different. Note both.

### 4. Persona reverse-audit

Build one concrete user with:
- Name, age, location, working style
- Specific stack (e.g. "TypeScript + Tauri + Rust, ~40k LOC, 1.5 years old")
- Primary pain point that brought them to this tool
- Specific competitors they tried and rejected, with reasons
- A 30-day usage timeline: Day 1 (first try), Day 7 (first win), Day 14
  (first real friction), Day 30 (would they recommend?)

Then walk every recent feature slice through this persona. For each slice,
mark: does it directly help this user? indirectly? not at all?

If most recent slices score "not at all", the project is building tools
faster than it's earning users.

### 5. Output the five-dimension scorecard

| Dimension | What you score |
|---|---|
| Engineering execution | Architecture, tests, mypy/lint, code organization |
| Engineering culture | Honesty in comments, retrospectives, OpenSpec discipline |
| Product definition | Is "who is this for, what are they doing" clear? |
| Evaluation capability | Can you measure if the product is actually working? |
| Long-term maintainability | What gets harder over time? |

Each dimension gets a letter grade with **one specific piece of evidence**.

### 6. Three sharp questions

End with three questions, not a summary. The questions should:
- Force a choice the user has been avoiding
- Be answerable in one sentence (not "should we add X feature?")
- Hurt to answer if the answer is honest

Good examples:
- "If you shut this down today, who would notice?"
- "What's your auto-confirm accuracy rate?"
- "What does this do that mem0 doesn't?"

Bad examples:
- "How can we improve documentation?" (too soft)
- "What's your roadmap for v2?" (asking, not challenging)

---

## Output Template

```markdown
## 一句话评级
[One sentence. Often "X is stronger than Y".]

## 真正做得好的地方
[2-4 items, each with concrete evidence — file paths, line counts, specific
patterns. Not adjectives.]

## 我看到的真实风险
[4-6 items, ranked roughly by severity. Each with file/line evidence.]

## 给你的三个尖锐问题
[Three questions. Not advice.]

## 总分
- 工程实施: A/B/C with one-line evidence
- 工程文化: ...
- 产品定义: ...
- 评估能力: ...
- 长期可维护性: ...

## 综合
[Final tier with the conditional: "if you do X, you'd be at A; if you keep
doing Y, the floor will erode."]
```

---

## Reverse Audit Through Persona (separate output, can be deferred)

When the user asks for the persona-driven audit (or you decide it's needed
to make risks concrete), output:

```markdown
## 编一个真实用户：[name]

### 角色卡
[Specific person with stack, pain, prior tools tried]

### 30 天使用流
- Day 1: ... 🚨 第一个卡点：...
- Day 7: ... (first win)
- Day 14: ... 🚨 第二个卡点：...
- Day 30: ... (would they recommend?)

### 这个 persona 暴露的真问题
| 优先级 | 问题 | 当前架构无法解决，需要改什么 |
|---|---|---|
| P0 | ... | ... |
| P1 | ... | ... |
| P2 | ... | ... |

### 用 persona 反向 audit 功能切片
- vX.Y feature A: 用得上 / 用不上 / 用得上但需要 Z 先跑通
- ...
- 总共 N 个切片中 M 个对这个 persona 直接产生价值
```

---

## Anti-patterns to refuse

- **Don't grade A unless every dimension has concrete evidence.** Default
  to A- when a dimension is strong but you can name one specific weakness.
- **Don't write a summary that softens the audit.** "Overall the project
  is doing great with some minor issues" is the failure mode.
- **Don't merge findings into one paragraph.** Risks and strengths must be
  enumerable, scannable, and individually actionable.
- **Don't propose fixes inside the audit.** That's the next conversation.
  The audit's job is to make the right next conversation possible.
- **Don't skip running the actual tests / linter / type checker.** "I think
  the codebase looks healthy" is a vibe, not an audit.

---

## When NOT to use this skill

- User asks about a single bug, feature, or file. Use normal investigation.
- User explicitly wants validation ("我们做得好不好？" can mean either —
  default to honest audit unless the user clarifies).
- The project is < 1 month old or < 500 LOC. Audit overhead exceeds value.

If unsure, ask: "Do you want an honest audit (might find uncomfortable
things) or a quick read on a specific concern?"
