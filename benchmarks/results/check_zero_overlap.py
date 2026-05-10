"""Check: for zero-recall cases in current Hybrid, how many are pool-misses vs FTS-misses?"""
import json
import re

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

with open("benchmarks/results/results_harness_hybrid_top5_20260427_0401.json") as f:
    r = json.load(f)

data_path = "C:/Users/ManHua/AppData/Local/Temp/longmemeval_s_cleaned.json"
with open(data_path, encoding="utf-8") as f:
    full_data = json.load(f)
data_by_qid = {e["question_id"]: e for e in full_data}

zero = [x for x in r["results"] if x["recall"] == 0]
print(f"Zero recall: {len(zero)}")

# For each zero case, check if the correct session has token overlap
has_overlap = 0
no_overlap = 0
for x in zero:
    entry = data_by_qid.get(x["question_id"], {})
    haystack_sids = entry.get("haystack_session_ids", [])
    haystack_sessions = entry.get("haystack_sessions", [])
    tokens = tokenize(entry.get("question", ""))
    answer_ids = set(x["answer_session_ids"])

    found = False
    for i, sid in enumerate(haystack_sids):
        if sid not in answer_ids:
            continue
        turns = haystack_sessions[i]
        user_text = " ".join(t["content"].lower() for t in turns if t.get("role") == "user")
        for tok in tokens:
            if tok.lower() in user_text:
                found = True
                break
    if found:
        has_overlap += 1
    else:
        no_overlap += 1

print(f"  Has token overlap (FTS should find them): {has_overlap}")
print(f"  NO token overlap (truly semantic gap): {no_overlap}")

# For overlap cases: how many tokens match?
print("\nToken overlap for zero-recall cases:")
for x in zero[:10]:
    entry = data_by_qid.get(x["question_id"], {})
    haystack_sids = entry.get("haystack_session_ids", [])
    haystack_sessions = entry.get("haystack_sessions", [])
    tokens = tokenize(entry.get("question", ""))
    answer_ids = set(x["answer_session_ids"])

    best_match = 0
    best_sid = ""
    for i, sid in enumerate(haystack_sids):
        if sid not in answer_ids:
            continue
        turns = haystack_sessions[i]
        user_text = " ".join(t["content"].lower() for t in turns if t.get("role") == "user")
        matches = [tok for tok in tokens if tok.lower() in user_text]
        if len(matches) > best_match:
            best_match = len(matches)
            best_sid = sid

    print(f"\n  [{x['question_type'][:20]}] {x['question'][:60]}")
    print(f"    tokens ({len(tokens)}): {tokens}")
    print(f"    best overlap: {best_match} tokens (session {best_sid[:20]})")
