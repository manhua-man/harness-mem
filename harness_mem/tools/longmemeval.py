"""
harness-mem × LongMemEval Benchmark
===================================

Evaluates harness-mem's retrieval against the LongMemEval benchmark.

Modes:
    raw       — baseline: SQLite FTS5 keyword search
    hybrid    — FTS5 + keyword/person/quote boosting

Usage:
    python -m harness_mem.tools.longmemeval /tmp/longmemeval_s_cleaned.json
    python -m harness_mem.tools.longmemeval /tmp/longmemeval_s_cleaned.json --mode raw --limit 20
    python -m harness_mem.tools.longmemeval /tmp/longmemeval_s_cleaned.json --mode hybrid --limit 20
"""

from __future__ import annotations
import argparse
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4


# =============================================================================
# METRICS
# =============================================================================


def dcg(relevances: list[float], k: int) -> float:
    score = 0.0
    for i, rel in enumerate(relevances[:k]):
        score += rel / math.log2(i + 2)
    return score


def ndcg(rankings: list[int], correct_ids: set[str], corpus_ids: list[str], k: int) -> float:
    relevances = [1.0 if corpus_ids[idx] in correct_ids else 0.0 for idx in rankings[:k]]
    ideal = sorted(relevances, reverse=True)
    idcg = dcg(ideal, k)
    if idcg == 0:
        return 0.0
    return dcg(relevances, k) / idcg


def compute_recall(retrieved_ids: list[str], correct_ids: set[str]) -> float:
    if not correct_ids:
        return 1.0
    found = sum(1 for cid in correct_ids if cid in retrieved_ids)
    return found / len(correct_ids)


# =============================================================================
# HYBRID SCORING HELPERS (from mempalace longmemeval_bench.py)
# =============================================================================


STOP_WORDS = {
    "what", "when", "where", "who", "how", "which", "did", "do", "was", "were",
    "have", "has", "had", "is", "are", "the", "a", "an", "my", "me", "i", "you",
    "your", "their", "it", "its", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "ago", "last", "that", "this", "there", "about", "get", "got",
    "give", "gave", "buy", "bought", "made", "make", "said",
}

NOT_NAMES = {
    "What", "When", "Where", "Who", "How", "Which", "Did", "Do", "Was", "Were",
    "Have", "Has", "Had", "Is", "Are", "The", "My", "Our", "Their", "Can",
    "Could", "Would", "Should", "Will", "Shall", "May", "Might", "Monday",
    "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "June", "July", "August",
    "September", "October", "November", "December", "In", "On", "At", "For",
    "To", "Of", "With", "By", "From", "And", "But", "I", "It", "Its",
    "This", "That", "These", "Those", "Previously", "Recently", "Also",
    "Just", "Very", "More", "Said", "Speaker", "Person", "Time", "Date",
    "Year", "Day",
}


def _kw(text: str) -> list[str]:
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())
    return [w for w in words if w not in STOP_WORDS]


def _kw_overlap(query_kws: list[str], doc_text: str) -> float:
    doc_lower = doc_text.lower()
    if not query_kws:
        return 0.0
    hits = sum(1 for kw in query_kws if kw in doc_lower)
    return hits / len(query_kws)


def _quoted_phrases(text: str) -> list[str]:
    phrases = []
    for pat in [r"'([^']{3,60})'", r'"([^"]{3,60})"']:
        phrases.extend(re.findall(pat, text))
    return [p.strip() for p in phrases if len(p.strip()) >= 3]


def _quoted_boost(phrases: list[str], doc_text: str) -> float:
    if not phrases:
        return 0.0
    doc_lower = doc_text.lower()
    hits = sum(1 for p in phrases if p.lower() in doc_lower)
    return min(hits / len(phrases), 1.0)


def _person_names(text: str) -> list[str]:
    words = re.findall(r"\b[A-Z][a-z]{2,15}\b", text)
    return list(set(w for w in words if w not in NOT_NAMES))


def _name_boost(names: list[str], doc_text: str) -> float:
    if not names:
        return 0.0
    doc_lower = doc_text.lower()
    hits = sum(1 for n in names if n.lower() in doc_lower)
    return min(hits / len(names), 1.0)


# =============================================================================
# HARNESS-MEM BACKEND (lightweight, per-question)
# =============================================================================


class BenchVerbatimStore:
    """Minimal verbatim store for benchmarking: JSON blobs + SQLite FTS5.

    This is a simplified standalone version — does NOT depend on the full
    harness_mem.storage backend, to keep benchmarks independent.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.blob_dir = os.path.join(os.path.dirname(db_path), "blobs")
        os.makedirs(self.blob_dir, exist_ok=True)
        self._init_db()
        self._lock = threading.Lock()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA mmap_size=268435456")
        conn.execute("CREATE TABLE IF NOT EXISTS obs_index (id TEXT, session_id TEXT, raw_content TEXT)")
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS obs_fts USING fts5(raw_content, content=obs_index, content_rowid=rowid)")
        conn.execute("CREATE TABLE IF NOT EXISTS obs_meta (id TEXT PRIMARY KEY, session_id TEXT, timestamp TEXT)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON obs_index(session_id)")
        conn.commit()
        conn.close()

    def add(self, obs_id: str, session_id: str, raw_content: str, timestamp: str):
        # Store blob keyed by session_id so hybrid_search can find it
        blob_path = os.path.join(self.blob_dir, f"{session_id}.json")
        with open(blob_path, "w", encoding="utf-8") as f:
            json.dump({"id": obs_id, "session_id": session_id, "raw_content": raw_content, "timestamp": timestamp}, f)

        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            try:
                conn.execute("INSERT OR IGNORE INTO obs_index (id, session_id, raw_content) VALUES (?, ?, ?)",
                             (obs_id, session_id, raw_content))
                rowid = conn.execute("SELECT rowid FROM obs_index WHERE id=?", (obs_id,)).fetchone()[0]
                conn.execute("INSERT OR REPLACE INTO obs_meta (id, session_id, timestamp) VALUES (?, ?, ?)",
                             (obs_id, session_id, timestamp))
                conn.execute("INSERT INTO obs_fts(rowid, raw_content) VALUES (?, ?)", (rowid, raw_content))
                conn.commit()
            finally:
                conn.close()

    def _tokenize(self, text: str) -> list[str]:
        """Split query into tokens, filter out FTS5 stop words."""
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
        tokens = cleaned.split()
        return [t for t in tokens if t.lower() not in STOP_WORDS]

    def _make_fts_query(self, query: str) -> str:
        """Convert a natural-language query to an FTS5 query string.

        FTS5 query syntax: space-separated tokens are OR'd.
        Strip punctuation and special chars that confuse the parser (? ! . , etc.)
        """
        # Remove FTS5 special chars; keep alphanumerics and spaces
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", query)
        tokens = cleaned.split()
        return " ".join(tokens)

    def search(self, query: str, limit: int = 20) -> list[tuple[str, float]]:
        """Search using individual non-stop-word tokens, aggregate by session.

        FTS5 stop words cause queries like 'what did I' to return nothing.
        Instead, search each non-stop-word token separately and merge results.
        """
        tokens = self._tokenize(query)
        if not tokens:
            return []

        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            try:
                # Search each token individually and collect all hits
                session_scores: dict[str, float] = {}
                for token in tokens:
                    cursor = conn.execute("""
                        SELECT o.id, o.session_id, o.raw_content,
                               bm25(obs_fts) as score
                        FROM obs_fts f
                        JOIN obs_index o ON f.rowid = o.rowid
                        WHERE obs_fts MATCH ?
                        ORDER BY score
                        LIMIT ?
                    """, (token, limit * 3))
                    rows = cursor.fetchall()
                    for row in rows:
                        obs_id, session_id, content, score = row
                        if session_id not in session_scores:
                            session_scores[session_id] = score
                        # Keep best (lowest/most negative = best BM25) score
                        if score < session_scores[session_id]:
                            session_scores[session_id] = score
            finally:
                conn.close()

        # Sort by score (lower BM25 = better) and dedupe
        sorted_sessions = sorted(session_scores.items(), key=lambda x: x[1])
        return [(sid, score) for sid, score in sorted_sessions[:limit]]

    def hybrid_search(self, query: str, limit: int = 20,
                      query_date: str | None = None,
                      corpus_dates: dict[str, str] | None = None) -> list[tuple[str, float]]:
        """FTS5 + keyword/person/quote boosting."""
        # Step 1: get raw FTS results (more candidates)
        raw = self.search(query, limit=limit * 3)
        if not raw:
            return []

        # Parse query features
        names = _person_names(query)
        all_kws = _kw(query)
        predicate_kws = [w for w in all_kws if w not in {n.lower() for n in names}]
        quoted = _quoted_phrases(query)

        scored = []
        for session_id, fts_score in raw:
            # BM25 is negative; better matches have more negative scores.
            # Convert to positive: higher fused = better match.
            bm25_pos = abs(fts_score)

            blob_path = os.path.join(self.blob_dir, f"{session_id}.json")
            content = ""
            if os.path.exists(blob_path):
                with open(blob_path) as f:
                    content = json.load(f).get("raw_content", "")

            pred_overlap = _kw_overlap(predicate_kws, content)
            q_boost = _quoted_boost(quoted, content)
            n_boost = _name_boost(names, content)

            # Additive boost: BM25 base + keyword/person/quote/temporal signals
            # Multipliers in [0,1] subtracted from bm25_pos to reward better matches.
            fused = bm25_pos
            fused -= 0.30 * pred_overlap        # keyword overlap reward
            fused -= 0.40 * q_boost             # quoted phrase reward
            fused -= 0.15 * n_boost             # person name reward

            # Temporal proximity reward (within 30 days)
            if corpus_dates and query_date and session_id in corpus_dates:
                sess_date = corpus_dates.get(session_id, "")
                if sess_date and query_date:
                    try:
                        qd = datetime.fromisoformat(query_date.replace("Z", "+00:00"))
                        sd = datetime.fromisoformat(sess_date.replace("Z", "+00:00"))
                        days_diff = abs((qd - sd).days)
                        if days_diff <= 30:
                            fused -= 0.20 * (1.0 - days_diff / 30.0)
                    except (ValueError, TypeError):
                        pass

            scored.append((session_id, fused))

        scored.sort(key=lambda x: -x[1])
        return scored[:limit]


# =============================================================================
# BENCHMARK RUNNER
# =============================================================================


def run_benchmark(
    data_path: str,
    mode: str = "raw",
    limit: int = 0,
    top_k: int = 5,
    out_file: str | None = None,
) -> float:
    print(f"\n{'=' * 60}")
    print("  harness-mem × LongMemEval Benchmark")
    print(f"{'=' * 60}")
    print(f"  Data:        {Path(data_path).name}")
    print(f"  Mode:        {mode}")
    print(f"  Top-K:       {top_k}")
    print(f"  Limit:       {limit or 'all'}")
    print(f"{'─' * 60}\n")

    # Load JSON
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    if limit > 0:
        data = data[:limit]

    all_recall = []
    per_type: dict[str, list[float]] = defaultdict(list)
    results_log = []
    start_time = datetime.now()

    for idx, entry in enumerate(data):
        question_id = entry["question_id"]
        question_type = entry["question_type"]
        question = entry["question"]
        question_date = entry.get("question_date", "")
        answer_session_ids = set(entry["answer_session_ids"])
        haystack_session_ids = entry["haystack_session_ids"]
        haystack_sessions = entry["haystack_sessions"]
        haystack_dates = entry.get("haystack_dates", [""] * len(haystack_session_ids))

        print(f"[{idx + 1}/{len(data)}] {question_type[:20]:20s} | {question[:60]}")

        # Build corpus: one doc per session (session-level granularity)
        corpus_ids = []
        corpus_texts = []
        corpus_dates = {}

        for sess_id, session, date in zip(haystack_session_ids, haystack_sessions, haystack_dates):
            user_turns = [t["content"] for t in session if t.get("role") == "user"]
            if user_turns:
                doc = "\n".join(user_turns)
                corpus_ids.append(sess_id)
                corpus_texts.append(doc)
                corpus_dates[sess_id] = date

        if not corpus_ids:
            continue

        # Create temp backend for this question
        tmpdir = tempfile.mkdtemp(prefix="hm_lme_")
        try:
            db_path = os.path.join(tmpdir, "bench.sqlite")
            store = BenchVerbatimStore(db_path)

            # Ingest all sessions as Observations
            for sess_id, text in zip(corpus_ids, corpus_texts):
                obs_id = str(uuid4())
                timestamp = corpus_dates.get(sess_id, datetime.now().isoformat())
                store.add(obs_id, sess_id, text, timestamp)

            # Search
            if mode == "raw":
                raw_results = store.search(question, limit=top_k)
                retrieved_ids = [sid for sid, _ in raw_results]
            else:  # hybrid
                hybrid_results = store.hybrid_search(
                    question, limit=top_k,
                    query_date=question_date,
                    corpus_dates=corpus_dates,
                )
                retrieved_ids = [sid for sid, _ in hybrid_results]

            # Compute metrics
            recall = compute_recall(retrieved_ids, answer_session_ids)
            all_recall.append(recall)
            per_type[question_type].append(recall)

            results_log.append({
                "question_id": question_id,
                "question_type": question_type,
                "question": question,
                "answer_session_ids": list(answer_session_ids),
                "retrieved_ids": retrieved_ids,
                "recall": recall,
            })

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    elapsed = (datetime.now() - start_time).total_seconds()
    avg_recall = sum(all_recall) / len(all_recall) if all_recall else 0

    print(f"\n{'=' * 60}")
    print(f"  RESULTS — harness-mem ({mode}, top-{top_k})")
    print(f"{'=' * 60}")
    print(f"  Time:        {elapsed:.1f}s ({elapsed / max(len(data), 1):.2f}s per question)")
    print(f"  Questions:   {len(data)}")
    print(f"  Avg Recall:  {avg_recall:.3f}")

    print("\n  PER-TYPE RECALL:")
    for qtype in sorted(per_type.keys()):
        vals = per_type[qtype]
        avg = sum(vals) / len(vals)
        print(f"    {qtype:30s} R@{top_k}={avg:.3f}  (n={len(vals)})")

    perfect = sum(1 for r in all_recall if r >= 1.0)
    partial = sum(1 for r in all_recall if 0 < r < 1.0)
    zero = sum(1 for r in all_recall if r == 0)
    print("\n  RECALL DISTRIBUTION:")
    print(f"    Perfect (1.0):  {perfect:4d} ({perfect / len(all_recall) * 100:.1f}%)")
    print(f"    Partial (0-1):  {partial:4d} ({partial / len(all_recall) * 100:.1f}%)")
    print(f"    Zero (0.0):     {zero:4d} ({zero / len(all_recall) * 100:.1f}%)")
    print(f"\n{'=' * 60}\n")

    if out_file:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump({
                "mode": mode,
                "top_k": top_k,
                "total_questions": len(data),
                "avg_recall": avg_recall,
                "per_type": {k: sum(v) / len(v) for k, v in per_type.items()},
                "results": results_log,
            }, f, indent=2)
        print(f"  Results saved to: {out_file}")

    return avg_recall


def default_output_path(mode: str, top_k: int, now: datetime | None = None) -> Path:
    """Return the default output path for benchmark results."""
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M")
    tag = f"_{mode}" if mode != "raw" else ""
    return Path.cwd() / f"results_harness{tag}_top{top_k}_{timestamp}.json"


# =============================================================================
# CLI
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="harness-mem × LongMemEval Benchmark")
    parser.add_argument("data_file", help="Path to longmemeval_s_cleaned.json")
    parser.add_argument("--mode", choices=["raw", "hybrid"], default="raw",
                        help="Retrieval mode: raw (FTS) or hybrid (FTS+boosting)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit to N questions (default: all)")
    parser.add_argument("--top-k", type=int, default=5,
                        help="Top-K retrieval (default: 5)")
    parser.add_argument("--out", default=None, help="Output JSON file")
    args = parser.parse_args()

    if not args.out:
        args.out = str(default_output_path(args.mode, args.top_k))

    run_benchmark(
        args.data_file,
        args.mode,
        args.limit,
        args.top_k,
        args.out,
    )


if __name__ == "__main__":
    main()
