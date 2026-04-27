"""Diagnose Hybrid: where do correct sessions rank?"""
import json

with open("benchmarks/results/results_real_hybrid_rrf_r5.json") as f:
    r = json.load(f)

# For zero recall: correct session rank in retrieved (or 'not retrieved')
zero = [x for x in r["results"] if x["recall"] == 0]
print(f"Zero recall: {len(zero)}")
for x in zero[:6]:
    retrieved = x["retrieved_ids"]
    correct = set(x["answer_session_ids"])
    # Check if correct is in retrieved
    in_retrieved = [cid for cid in retrieved if cid in correct]
    missed = [cid for cid in correct if cid not in retrieved]
    print(f"\n  Q: {x['question'][:70]}")
    print(f"  In top-5: {in_retrieved}")
    print(f"  Missed: {missed}")
    # Check top-20 if available
    print(f"  Retrieved top-5: {retrieved}")

print(f"\n\n{'='*70}")
print("Looking at cases where correct session IS retrieved but NOT in top-5:")
print("="*70)
count = 0
for x in r["results"]:
    retrieved = x["retrieved_ids"]
    correct = set(x["answer_session_ids"])
    in_ret = [cid for cid in retrieved if cid in correct]
    if in_ret and x["recall"] < 1.0:
        count += 1
        if count <= 10:
            n_correct = len(correct)
            n_found = len(in_ret)
            n_missed = n_correct - n_found
            print(f"\n[{x['question_type']}] {x['question'][:70]}")
            print(f"  {n_found}/{n_correct} found, {n_missed} missed (recall={x['recall']:.2f})")
            print(f"  Found: {in_ret}")

print(f"\nTotal cases with some correct retrieved but recall < 1.0: {count}")
