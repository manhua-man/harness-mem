"""Diagnose Hybrid: for partial cases, how far is the missed session?"""
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

with open("benchmarks/results/results_real_hybrid_rrf_r5.json") as f:
    r = json.load(f)

data_path = "C:/Users/ManHua/AppData/Local/Temp/longmemeval_s_cleaned.json"
with open(data_path, encoding="utf-8") as f:
    full_data = json.load(f)
data_by_qid = {e["question_id"]: e for e in full_data}

partial = [x for x in r["results"] if 0 < x["recall"] < 1]

# For each partial, find missed sessions that have token overlap
missed_but_overlap = []
missed_no_overlap = []
zero_has_overlap = []
zero_no_overlap = []

all_zero = [x for x in r["results"] if x["recall"] == 0]

def get_overlap(qid):
    entry = data_by_qid.get(qid, {})
    haystack_sids = entry.get("haystack_session_ids", [])
    haystack_sessions = entry.get("haystack_sessions", [])
    tokens = tokenize(entry.get("question", ""))
    overlap_map = {}
    for i, sid in enumerate(haystack_sids):
        turns = haystack_sessions[i]
        user_text = " ".join(t["content"].lower() for t in turns if t.get("role") == "user")
        matches = [t for t in tokens if t.lower() in user_text]
        overlap_map[sid] = matches
    return overlap_map

# Zero recall analysis
for x in all_zero:
    overlap = get_overlap(x["question_id"])
    answer_ids = set(x["answer_session_ids"])
    has_overlap = any(overlap.get(sid) for sid in answer_ids)
    if has_overlap:
        zero_has_overlap.append(x)
    else:
        zero_no_overlap.append(x)

# Partial recall analysis
for x in partial:
    overlap = get_overlap(x["question_id"])
    retrieved = set(x["retrieved_ids"])
    answer_ids = set(x["answer_session_ids"])
    missed = answer_ids - retrieved
    has_overlap = any(overlap.get(sid) for sid in missed)
    if has_overlap:
        missed_but_overlap.append((x, [overlap.get(sid) for sid in missed if overlap.get(sid)]))
    else:
        missed_no_overlap.append(x)

print(f"=== ZERO RECALL ({len(all_zero)} cases) ===")
print(f"  Has token overlap with answer session: {len(zero_has_overlap)}")
print(f"  NO token overlap: {len(zero_no_overlap)}")
print()
print(f"=== PARTIAL RECALL ({len(partial)} cases) ===")
print(f"  Missed sessions HAVE token overlap: {len(missed_but_overlap)}")
print(f"  Missed sessions NO token overlap: {len(missed_no_overlap)}")
print()

# Show examples where missed sessions have overlap (retrievable)
print("=== MISSED BUT HAS OVERLAP (fixable by limit increase?) ===")
for x, overlaps in missed_but_overlap[:8]:
    tokens = tokenize(data_by_qid.get(x["question_id"], {}).get("question", ""))
    missed = set(x["answer_session_ids"]) - set(x["retrieved_ids"])
    print(f"\n[{x['question_type']}] {x['question'][:65]}")
    print(f"  Tokens: {tokens}")
    print(f"  Missed overlap: {overlaps}")
    print(f"  Recall: {x['recall']:.2f} ({int(x['recall']*len(x['answer_session_ids']))}/{len(x['answer_session_ids'])})")
