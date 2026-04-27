import json
from collections import Counter

with open("benchmarks/results/results_harness_raw_r5.json") as f:
    r = json.load(f)

zero = [x for x in r["results"] if x["recall"] == 0]
print(f"Total zero recall: {len(zero)}")
by_type = Counter(x["question_type"] for x in zero)
for t, c in by_type.most_common():
    print(f"  {t}: {c}")

print()
print("--- Examples ---")
for x in zero[:6]:
    print(f"[{x['question_type']}] Q: {x['question']}")
    print(f"  Retrieved: {x['retrieved_ids']}")
    print(f"  Answer in: {x['answer_session_ids']}")
    print()
