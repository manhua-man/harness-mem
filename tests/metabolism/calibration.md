# Metabolism Suggestion Threshold Calibration

> v2.3.1 calibration sweep — documents that the three core thresholds
> produce expected candidate counts on seeded fixture data.

## Thresholds Under Test

| Parameter | Default | Source |
|-----------|---------|--------|
| `similarity_threshold` | 0.85 | `select_metabolism_pass()` kwarg |
| `stale_silence_days` | 60 | `select_metabolism_pass()` kwarg |
| `REPEAT_BOOST_BASE` | 0.1 | `harness_mem/read_api.py` module constant |
| `REPEAT_BOOST_WINDOW_DAYS` | 7 | `harness_mem/read_api.py` module constant |
| `REPEAT_BOOST_MIN_HITS` | 2 | `harness_mem/read_api.py` module constant |

## Calibration Fixture

Seeded data (run via `select_metabolism_pass` with default `ReplayBudget`):

- **3 near-duplicate entry pairs** (each with 2 `search_hit` signals)
- **4 stale entries** at 90d, 75d, 65d, 61d silence
- **2 stale rules** at 80d, 62d silence
- **1 fresh entry** with recent `wake_surfaced` signal (0d silence)
- **1 borderline entry** at 59d silence (below threshold)

## Results

### Merge (similarity ≥ 0.85)

| Pair | Similarity | Evidence Signals | Verdict |
|------|-----------|-----------------|---------|
| SQL parameterization variants | 0.9707 | 4 | PASS — well above 0.85 |
| pytest convention variants | 0.9374 | 4 | PASS — above 0.85 |
| Pydantic schema variants | 0.8872 | 4 | PASS — above 0.85 |

**Total merge candidates: 3** (all 3 seeded pairs detected)

### Stale (silence ≥ 60d)

| Target Kind | Days Since Last Surface | Verdict |
|-------------|------------------------|---------|
| memory_entry | 90 | PASS — well above 60d |
| confirmed_rule | 80 | PASS — above 60d |
| memory_entry | 75 | PASS — above 60d |
| memory_entry | 65 | PASS — above 60d |
| confirmed_rule | 62 | PASS — above 60d |
| memory_entry | 61 | PASS — above 60d |

**Total stale candidates: 6** (4 entries + 2 rules)

**Correctly excluded:**
- Fresh entry (0d silence) — not stale
- Borderline entry (59d silence) — below 60d threshold

### Supersede (deferred)

**Total supersede candidates: 0** — intentionally deferred in v2.3.1.
Contract test confirms proposer returns `[]` even when `historical_truths`
dimension is populated.

### Repeat Boost (search re-ranking)

Verified via `tests/commands/test_signal_influence.py`:

| Condition | Boost Applied | Verdict |
|-----------|--------------|---------|
| `weak_link_signals=True` + ≥2 hits in 7d | +0.1 (`REPEAT_BOOST_BASE`) | PASS |
| `weak_link_signals=True` + <2 hits in 7d | 0.0 | PASS — below min_hits |
| `weak_link_signals=False` (any hit count) | 0.0 | PASS — flag off |

## Test Coverage

| Test File | Covers |
|-----------|--------|
| `tests/commands/test_metabolism_pass.py` (4 tests) | Merge, stale, supersede proposers + integration |
| `tests/commands/test_signal_influence.py` | Repeat boost on/off, wake re-grouping |
| `tests/loop_harness/test_auto_confirm_calibration.py` | Auto-confirm calibration |
| `tests/loop_harness/` (28 tests total) | v2.2 contract preserved after weak-link changes |

## Conclusion

All three suggestion thresholds produce expected counts on seeded data:

- **similarity 0.85**: catches semantically near-duplicate pairs (sim range
  0.89–0.97 on test fixtures) without false positives on unrelated entries.
- **silence 60d**: correctly identifies long-silent truths while excluding
  fresh and borderline (59d) entries.
- **repeat boost 0.1**: additive score bump applied only when the entry has
  ≥2 search_hits in the last 7 days AND the project profile flag is enabled.

No threshold adjustments needed for v2.3.1. The `supersede` leg remains a
stub pending a distinguishing signal spec in v2.3.2.

---

*Generated: v2.3.1 validation task 7.6*
*Model: all-MiniLM-L6-v2 (project default)*
*Platform: Python 3.13, Windows, pytest 8.4.2*
