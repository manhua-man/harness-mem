import json
import re

with open("benchmarks/results/results_harness_raw_r5.json") as f:
    r = json.load(f)

zero = [x for x in r["results"] if x["recall"] == 0]

# Simulate FTS tokenization on these questions
STOP_WORDS = {
    "what", "when", "where", "who", "how", "which", "did", "do", "was", "were",
    "have", "has", "had", "is", "are", "the", "a", "an", "my", "me", "i", "you",
    "your", "their", "it", "its", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "ago", "last", "that", "this", "there", "about", "get", "got",
    "give", "gave", "buy", "bought", "made", "make", "said",
}

def tokenize(q):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", q)
    tokens = cleaned.split()
    return [t for t in tokens if t.lower() not in STOP_WORDS and len(t) >= 2]

for x in zero[:10]:
    tokens = tokenize(x["question"])
    print(f"[{x['question_type']}] {x['question']}")
    print(f"  Tokens: {tokens}")
    print()
