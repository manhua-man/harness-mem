---
name: loop-evaluation-harness
description: |
  Build an end-to-end evaluation harness for a feature loop (not a unit
  test, not a single-shot benchmark). Use when the user asks "how do I
  measure if our memory/auth/sync loop actually works?", "我想测 AI 自动
  confirm 准确率", "feature 之间是否真的互相帮上忙了？" — anything that
  asks for measurable proof that a multi-step process holds together,
  not just that individual functions return the right thing.
license: MIT
metadata:
  author: harness-mem
  version: "1.0"
---

# Loop Evaluation Harness

There's a gap most projects don't know they have:

- **Unit tests** prove `f(x) == y` for individual functions.
- **Single-point benchmarks** prove "given input X, the system produces
  output Y with quality Q" (e.g. retrieval R@5).
- **Loop harnesses** prove the **steps connect**: A produces something
  B can use, B's decisions are reflected in C, C's effect is observable.

This skill builds the third kind. It's surprisingly rare. AI agent / RAG /
memory / sync / auth pipeline projects all need one and almost none have
one.

---

## When this is the right tool

Symptoms that tell you a loop harness is needed:

- The product narrative claims "X happens, then Y happens, then Z is
  better", but no single test proves Z actually became better.
- A feature was shipped and "works in unit tests" but you can't tell
  whether it's actually being used downstream.
- The project has accumulated multiple feature slices (v1.6, v1.7, v1.8...)
  and you're not sure if later slices depend on earlier slices working
  end-to-end, or if they're parallel features that happen to ship together.
- Someone asks "is this feature pulling its weight?" and the honest answer
  is "I don't know, no one measures that".

If the project has only unit tests and a benchmark, it almost certainly
needs a loop harness.

---

## Design Principles

### 1. Each scenario answers ONE business question

Not "tests function X". A business question. Examples:

- ❌ `test_distill_extract_returns_list_of_entries` — that's a unit test
- ✅ `test_distill_extraction_precision_recall_against_hand_labels` —
  business question: "what fraction of distill output is actually
  long-term knowledge vs noise?"

The scenario name should be a sentence a non-engineer could care about.

### 2. Real-style fixtures, never lorem ipsum

Fixtures must look like real production data: mixed signal and noise,
multi-paragraph, project-specific quirks. If you can't tell the fixture
apart from a real session log at a glance, it's good. If it reads like
"foo bar baz", redo it.

Hand-label what should and shouldn't be extracted. Two label sets:
- `expected_signals`: substrings that *should* appear in extraction output
- `expected_noise`: substrings that *should NOT* appear

The labels are the ground truth, not the test assertions. Assertions
score against the labels.

### 3. Loose floors, real numbers

Each scenario's assertions use **deliberately loose thresholds** so the
harness doesn't cry wolf. The real value is the actual numbers, printed
to stdout via a small `LoopMetrics` container, captured cross-version.

```python
@dataclass(frozen=True)
class LoopMetrics:
    name: str
    values: dict[str, float]
    def report(self) -> None:
        body = json.dumps(self.values, indent=2, sort_keys=True)
        print(f"\n[loop_harness:{self.name}] {body}")
```

Assertion floors typically:
- "anything was extracted" (count > 0)
- "less than 50% noise" (precision > 0.5)
- "less than 30% missed" (recall > 0.7)

The point is **catching collapse**, not policing 0.93 vs 0.95.

### 4. xfail is a feature, not a workaround

If a scenario depends on a capability that doesn't exist yet (e.g. "AI
auto-confirms low-risk candidates" lives only in a slash prompt, not a
real Python function), write the scenario anyway and `pytest.xfail` it
with a docstring that names the exact API needed to flip it green.

This makes technical debt **visible and measurable**. When the API
lands, removing xfail is a one-line proof the feature is real.

### 5. Data isolation, no LLM in CI

Use `tmp_path`, never write to the real user data dir. Don't depend on
LLMs in the harness itself — that's flaky and slow. The LLM-facing path
should have its own validation (skill tests, prompt eval).

The loop harness is the **deterministic floor** that proves the wiring
holds, regardless of which model is in the LLM seat.

---

## Process

### 1. Map the loop

Before writing any test, sketch the loop on paper / in a comment:

```
input source
  → step A (transform)
  → step B (decide / filter)
  → step C (apply)
  → observable effect
```

For each arrow, ask: "what's the contract?" That's a candidate scenario.

### 2. Pick 4-6 scenarios that span the loop

Not one per step — pick the ones that catch loop collapse. Common shapes:

| Shape | Example |
|---|---|
| Quality of A's output | "distill extracts what's actually reusable" |
| B's calibration | "auto-review confirms what should be confirmed" |
| C's observable effect | "wake-up actually surfaces the rule" |
| Round-trip property | "supersede replaces current truth, history stays" |
| Counter / metadata | "rule's usage count increments when surfaced" |

Each scenario should be runnable in < 10 seconds.

### 3. Build shared fixtures + metrics helpers

Concrete pieces:

- `fixtures.py`: `LoopFixture` dataclass with id, input data, expected
  signals, expected noise. List-of-fixtures so adding cases is one entry.
- `conftest.py`: pytest fixture that materializes the inputs into the
  storage layout the system expects. `LoopMetrics` container.
  Helper functions like `precision_recall_f1(extracted, signals, noise)`.

### 4. Wire each scenario the same way

```python
def test_some_scenario(...):
    # 1. Set up: feed fixtures into the real system
    # 2. Drive the loop step you're measuring
    # 3. Read back the observable effect
    # 4. Compute metrics
    # 5. LoopMetrics(...).report()  ← prints actual numbers
    # 6. assert with loose floors  ← only catches collapse
```

### 5. Write a README that names the scope

The README tells you what the harness does NOT do. Always include:

- "What this harness solves vs what existing harness solves" (e.g. loop
  harness vs benchmark harness)
- A scenario table with current status (✅ real / ⚠️ xfail)
- "Cross-version comparison: how to use" (capture stdout, archive)
- "Design constraints" (real-style fixtures, no LLM, isolation)
- "Next steps not in this slice" — what scenarios you didn't build yet,
  with the reason

The README is the primary defense against scope creep.

---

## Output Layout

```
tests/loop_harness/
  __init__.py
  README.md                    ← scope, scenario table, design constraints
  fixtures.py                  ← LoopFixture dataclass + LOOP_FIXTURES list
  conftest.py                  ← shared pytest fixtures + LoopMetrics + scoring helpers
  test_<scenario_1>.py
  test_<scenario_2>.py
  ...
```

Register a marker (`loop_harness`) in `pytest.ini` so the harness can be
selected or skipped as a unit:

```ini
markers =
    loop_harness: end-to-end <product> loop scenarios
```

---

## Key Things This Skill Will Reveal (Use as Self-Check)

After running, the harness will surface real things you didn't know:

1. **Where the loop silently breaks.** A scenario you expected to pass
   fails. That's a real bug the unit tests didn't catch.
2. **Where the product narrative is unverifiable.** A capability the
   docs claim exists but you can't write a scenario for. That's a gap
   between marketing and reality.
3. **Where features depend on each other.** Setting up scenario N
   requires features 1..N-1 to work. If they don't, you find out now,
   not in production.
4. **Honest baselines for cross-version comparison.** Now you can answer
   "did we get better or worse?" with numbers, not vibes.

---

## Related Reality-Check Skills

This skill is one of three sharing the same evidence-over-narrative
discipline:

| Skill | When to use | Output |
|---|---|---|
| `project-honest-audit` | "How is this project doing overall?" — find risks before transition | Markdown audit report with scorecard |
| `loop-evaluation-harness` (this skill) | "Is our multi-step loop actually working end-to-end?" — instrument the loop | `tests/loop_harness/` test code + README |
| `multi-client-field-test` | "Will real users in each target client succeed?" — pre-release validation | Markdown persona packet at `docs/...-packet.md` |

A loop harness gives you deterministic numbers but doesn't tell you
whether the experience is usable from the outside. When an audit or
field test surfaces "the wiring works but users still bounce off", that's
typically a docs / prompt / setup issue this skill can't catch — escalate
to `multi-client-field-test`.

---

## Anti-patterns to refuse

- **Don't write a unit test in disguise.** If the scenario's assertion
  is `assert function_returns_correct_shape`, that's a unit test. Move
  it. Loop scenarios assert on **observable downstream effects**.
- **Don't use synthetic / lorem ipsum fixtures.** They hide the real
  noise problem.
- **Don't tighten the floors prematurely.** F1 ≥ 0.85 today might be
  a rebuild tomorrow. Print the actual number, only assert that it
  hasn't collapsed.
- **Don't hide tradeoffs to make numbers look good.** If improving
  precision dropped recall, the harness should report both — that's
  the data the user needs.
- **Don't put the LLM in the harness path.** The harness is the
  deterministic floor. LLM evaluation is a different artifact.
- **Don't skip the README.** A scenario directory without a README
  becomes scope creep within two weeks.

---

## When NOT to use this skill

- The project has < 3 connected features. The "loop" is too short to
  benefit from a harness this elaborate.
- The product is a one-shot transformation (input → output, no
  feedback). Use a benchmark, not a loop harness.
- The user wants a unit test, integration test, or smoke test. Those
  have their own skills / patterns. Loop harness is specifically for
  multi-step processes where the **connections** are what's at risk.

If unsure, ask: "Is the thing you want to measure a single function's
output, or whether multiple steps still hold hands?"
