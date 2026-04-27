"""
For zero-recall Hybrid cases: where does the correct session rank in raw FTS?
If correct session is NOT in top-500 of FTS, candidate pool size won't help.
If it IS in top-500, the fusion is the problem.
"""
import json, re, os, sqlite3, tempfile, shutil

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
    return [t for t in tokens if t.lower() not in STOP_WORDS]

with open("benchmarks/results/results_harness_hybrid_top5_20260427_0408.json") as f:
    r = json.load(f)

data_path = "C:/Users/ManHua/AppData/Local/Temp/longmemeval_s_cleaned.json"
with open(data_path, encoding="utf-8") as f:
    full_data = json.load(f)
data_by_qid = {e["question_id"]: e for e in full_data}

zero = [x for x in r["results"] if x["recall"] == 0]
print(f"Zero recall: {len(zero)}")

for x in zero:
    entry = data_by_qid.get(x["question_id"], {})
    tokens = tokenize(entry.get("question", ""))
    answer_ids = set(x["answer_session_ids"])

    # Build a single FTS query from all tokens
    query_str = " ".join(tokens) if tokens else ""
    if not query_str:
        print(f"\n[{x['question_type'][:15]}] {x['question'][:60]}")
        print(f"  NO TOKENS")
        continue

    # Get the same tmpdir used in the benchmark for this question
    # We'll just look at the raw FTS ranking in a fresh DB
    haystack_sids = entry.get("haystack_session_ids", [])
    haystack_sessions = entry.get("haystack_sessions", [])
    haystack_dates = entry.get("haystack_dates", [""] * len(haystack_sids))

    corpus_ids = []
    corpus_texts = []
    for sid, session, date in zip(haystack_sids, haystack_sessions, haystack_dates):
        user_turns = [t["content"] for t in session if t.get("role") == "user"]
        if user_turns:
            doc = "\n".join(user_turns)
            corpus_ids.append(sid)
            corpus_texts.append(doc)

    if not corpus_ids:
        continue

    tmpdir = tempfile.mkdtemp(prefix="hm_lme_check_")
    try:
        db_path = os.path.join(tmpdir, "bench.sqlite")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS observations (id TEXT, session_id TEXT, raw_content TEXT)")
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(raw_content, content=observations, content_rowid=rowid)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON observations(session_id)")

        for sid, text in zip(corpus_ids, corpus_texts):
            conn.execute("INSERT INTO observations (id, session_id, raw_content) VALUES (?, ?, ?)",
                        (sid, sid, text))
            rowid = conn.execute("SELECT rowid FROM observations WHERE id=?", (sid,)).fetchone()[0]
            conn.execute("INSERT INTO observations_fts(rowid, raw_content) VALUES (?, ?)", (rowid, text))
        conn.commit()

        # Query FTS and find where correct sessions rank
        cursor = conn.execute("""
            SELECT o.session_id, bm25(observations_fts) as score
            FROM observations_fts f
            JOIN observations o ON f.rowid = o.rowid
            WHERE observations_fts MATCH ?
            ORDER BY score
            LIMIT 500
        """, (query_str,))
        rows = cursor.fetchall()
        conn.close()

        ranks = {}
        for rank, (sid, score) in enumerate(rows):
            ranks[sid] = rank + 1  # 1-based

        found_ranks = {sid: ranks.get(sid, "NOT_IN_TOP_500") for sid in answer_ids}
        best_rank = min((r for r in found_ranks.values() if isinstance(r, int)), default=None)

        print(f"\n[{x['question_type'][:15]}] {x['question'][:60]}")
        print(f"  Tokens: {tokens}")
        print(f"  Answer ranks in FTS: {found_ranks}")
        print(f"  Best rank: {best_rank}")
        print(f"  Top-5 retrieved: {x['retrieved_ids'][:5]}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
