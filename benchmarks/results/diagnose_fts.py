"""
Analyze WHY FTS returns zero recall for each zero-recall case.
"""
import json, re

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

with open("benchmarks/results/results_harness_raw_r5.json") as f:
    r = json.load(f)

data_path = "C:/Users/ManHua/AppData/Local/Temp/longmemeval_s_cleaned.json"
with open(data_path, encoding="utf-8") as f:
    full_data = json.load(f)

data_by_qid = {e["question_id"]: e for e in full_data}

zero = [x for x in r["results"] if x["recall"] == 0]

NO_TOKENS = 0
SEMANTIC_GAP = 0
NO_OVERLAP = 0

for x in zero:
    qid = x["question_id"]
    entry = data_by_qid.get(qid, {})
    haystack_sids = entry.get("haystack_session_ids", [])
    haystack_sessions = entry.get("haystack_sessions", [])
    answer_ids = set(x["answer_session_ids"])
    tokens = tokenize(x["question"])

    matched_any = False
    for i, sid in enumerate(haystack_sids):
        if sid not in answer_ids:
            continue
        turns = haystack_sessions[i]
        user_turns = [t["content"].lower() for t in turns if t.get("role") == "user"]
        text = " ".join(user_turns)
        for tok in tokens:
            if tok.lower() in text:
                matched_any = True
                break

    if not tokens:
        NO_TOKENS += 1
    elif matched_any:
        NO_OVERLAP += 1
    else:
        SEMANTIC_GAP += 1

print(f"FTS Zero Recall Analysis ({len(zero)} cases)\n")
print(f"  NO_TOKENS      (query reduced to stopwords only): {NO_TOKENS}")
print(f"  SEMANTIC_GAP   (tokens exist, zero overlap in answer): {SEMANTIC_GAP}")
print(f"  NO_OVERLAP     (tokens overlap but FTS missed them): {NO_OVERLAP}")
print()

# Show semantic gap cases with context
print("=" * 70)
print("SEMANTIC_GAP cases (token overlap exists but FTS missed):")
print("=" * 70)
for x in zero:
    qid = x["question_id"]
    entry = data_by_qid.get(qid, {})
    haystack_sids = entry.get("haystack_session_ids", [])
    haystack_sessions = entry.get("haystack_sessions", [])
    answer_ids = set(x["answer_session_ids"])
    tokens = tokenize(x["question"])

    matched_any = False
    best_snippets = []
    for i, sid in enumerate(haystack_sids):
        if sid not in answer_ids:
            continue
        turns = haystack_sessions[i]
        user_turns = [t["content"] for t in turns if t.get("role") == "user"]
        text = " ".join(user_turns)
        matches = [t for t in tokens if t.lower() in text.lower()]
        if matches:
            matched_any = True
        # Find the first match in text
        snippet = text[:200].replace("\n", " ")
        best_snippets.append((sid, matches, snippet))

    if not tokens or matched_any:
        continue

    print(f"\n[{x['question_type']}] {x['question']}")
    print(f"  Tokens: {tokens}")
    for sid, matches, snippet in best_snippets:
        print(f"  [{sid}] matches={matches}")
        print(f"    snippet: {snippet}")
