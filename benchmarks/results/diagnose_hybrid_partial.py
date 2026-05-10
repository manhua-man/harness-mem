"""Diagnose Hybrid partial recall cases: rank 6-10 vs 91-100 gap."""
from collections import Counter
import json

with open("benchmarks/results/results_real_hybrid_rrf_r5.json") as f:
    r = json.load(f)

# Partial = 0 < recall < 1 (some but not all answer sessions found)
partial = [x for x in r["results"] if 0 < x["recall"] < 1]
print(f"Partial recall cases: {len(partial)}")

by_type = Counter(x["question_type"] for x in partial)
for t, c in by_type.most_common():
    print(f"  {t}: {c}")

# For each partial, how many answers were missed?
missed_counts = [len(x["answer_session_ids"]) - int(x["recall"] * len(x["answer_session_ids"])) for x in partial]
print(f"\nAverage answer sessions per partial case: {sum(len(x['answer_session_ids']) for x in partial) / len(partial):.1f}")

# How many partials are "close" (1 answer missed)?
close = [x for x in partial if len(x["answer_session_ids"]) == 1]
print(f"Partial with single answer: {len(close)}")

# Count how many partials are just 1 answer missed out of 1
print("\n--- Close misses (1 answer session, not recalled) ---")
close_missed = [x for x in partial if len(x["answer_session_ids"]) == 1 and x["recall"] == 0]
print(f"Total: {len(close_missed)}")
for x in close_missed[:5]:
    print(f"  Q: {x['question']}")
    print(f"  Retrieved: {x['retrieved_ids']}")

print("\n--- Multi-answer partials ---")
multi = [x for x in partial if len(x["answer_session_ids"]) > 1]
print(f"Total: {len(multi)}")
