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
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import Stemmer  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from harness_mem.storage.sqlite_index import SQLiteIndex

ps = Stemmer.Stemmer("porter")


# =============================================================================
# QUESTION TYPE REGISTRY (v1.6.0)
# =============================================================================

LONGMEMEVAL_QUESTION_TYPES: frozenset[str] = frozenset({
    "single-session-user",
    "single-session-preference",
    "single-session-assistant",
    "multi-session",
    "temporal-reasoning",
    "knowledge-update",
})
"""Registered LongMemEval question types as of v1.6.0.

This set is the canonical reference for the five-dimensions baseline (see
``docs/benchmark/v160-baseline.md`` and
``docs/benchmark/longmemeval-five-dimensions.md``). Any dataset entry whose
``question_type`` falls outside this set triggers a ``UserWarning`` via
:func:`_validate_question_types` but does NOT block the eval — unknown
dimensions are still scored and reported under their own bucket so a
new dataset version remains diagnosable, while drift from the registered set
remains visible to operators.
"""


def _validate_question_types(data: list[dict]) -> None:
    """Warn once per unknown question_type encountered in the dataset.

    Called once after JSON load — keeps the per-question hot loop free of
    extra string lookups while still providing operators a single audible
    signal when a dataset adds new dimensions.
    """
    seen: set[str] = set()
    for entry in data:
        qtype = entry.get("question_type")
        if qtype is None or qtype in seen:
            continue
        seen.add(qtype)
        if qtype not in LONGMEMEVAL_QUESTION_TYPES:
            warnings.warn(
                f"Unknown question_type {qtype!r} encountered; this "
                "dimension will be reported but is not part of the "
                "registered LONGMEMEVAL_QUESTION_TYPES set. Consider "
                "updating harness_mem/tools/longmemeval.py if this "
                "dimension is now stable.",
                UserWarning,
                stacklevel=2,
            )


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

ASSISTANT_RECALL_RE = re.compile(
    r"previous (?:chat|conversation)|our previous|"
    r"you (?:told|suggested|provided|recommended)|"
    r"remind me|we discussed|follow up|looking back|going back|revisit",
    re.IGNORECASE,
)


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


def _session_doc_for_query(session: list[dict], question: str) -> str:
    """Build the indexed session text for a benchmark query.

    Most LongMemEval personal-memory questions target user-authored facts, so
    user turns stay as the default. Questions that explicitly ask what the
    assistant previously said need assistant turns as retrievable evidence.
    """
    if ASSISTANT_RECALL_RE.search(question):
        turns = [
            f"{turn.get('role', '')}: {turn.get('content', '')}"
            for turn in session
            if turn.get("content")
        ]
    else:
        turns = [
            turn["content"]
            for turn in session
            if turn.get("role") == "user" and turn.get("content")
        ]
    return "\n".join(turns)


# =============================================================================
# HARNESS-MEM BACKEND (lightweight, per-question)
# =============================================================================


class BenchVerbatimStore:
    """Minimal verbatim store for benchmarking: JSON blobs + SQLite FTS5.

    This is a simplified standalone version — does NOT depend on the full
    harness_mem.storage backend, to keep benchmarks independent.
    """

    def __init__(self, db_path: str, *, persist_vectors: bool = False):
        self.db_path = db_path
        self.blob_dir = os.path.join(os.path.dirname(db_path), "blobs")
        os.makedirs(self.blob_dir, exist_ok=True)
        self._init_db()
        self._lock = threading.Lock()
        self._persist_vectors = persist_vectors
        self._vector_index: SQLiteIndex | None = None
        if persist_vectors:
            self._init_vector_index()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA mmap_size=268435456")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS observations "
            "(id TEXT, session_id TEXT, raw_content TEXT, timestamp TEXT)"
        )
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(raw_content, content=observations, content_rowid=rowid)")
        conn.execute("CREATE TABLE IF NOT EXISTS obs_meta (id TEXT PRIMARY KEY, session_id TEXT, timestamp TEXT)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON observations(session_id)")
        conn.commit()
        conn.close()

    def _init_vector_index(self) -> None:
        """Create the vec_embeddings table used by real hybrid search."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS vec_embeddings ("
                "entry_id TEXT PRIMARY KEY, "
                "model_id TEXT NOT NULL, "
                "model_version TEXT NOT NULL, "
                "embedding BLOB NOT NULL, "
                "created_at INTEGER NOT NULL"
                ")"
            )
            conn.commit()
        finally:
            conn.close()

        from harness_mem.storage.sqlite_index import SQLiteIndex

        self._vector_index = SQLiteIndex(Path(self.db_path))

    def close(self) -> None:
        if self._vector_index is not None:
            self._vector_index.close()

    def add(self, obs_id: str, session_id: str, raw_content: str, timestamp: str):
        # Store blob keyed by session_id so hybrid_search can find it
        blob_path = os.path.join(self.blob_dir, f"{session_id}.json")
        with open(blob_path, "w", encoding="utf-8") as f:
            json.dump({"id": obs_id, "session_id": session_id, "raw_content": raw_content, "timestamp": timestamp}, f)

        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO observations (id, session_id, raw_content, timestamp) "
                    "VALUES (?, ?, ?, ?)",
                    (obs_id, session_id, raw_content, timestamp),
                )
                rowid = conn.execute("SELECT rowid FROM observations WHERE id=?", (obs_id,)).fetchone()[0]
                conn.execute("INSERT OR REPLACE INTO obs_meta (id, session_id, timestamp) VALUES (?, ?, ?)",
                             (obs_id, session_id, timestamp))
                conn.execute("INSERT INTO observations_fts(rowid, raw_content) VALUES (?, ?)", (rowid, raw_content))
                conn.commit()
            finally:
                conn.close()

        if self._persist_vectors and self._vector_index is not None:
            from harness_mem.commands.support import get_embedding_model_id

            model_id = get_embedding_model_id()
            self._vector_index.persist_embedding(obs_id, raw_content, model_id)

    def _tokenize(self, text: str) -> list[str]:
        """Split query into tokens, filter out stop words."""
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
        tokens = cleaned.split()
        return [t for t in tokens if t.lower() not in STOP_WORDS]

    def _expand_query(self, text: str) -> tuple[list[str], list[str]]:
        """Return (primary, fallback) fragments with stemming expansion.

        Primary: original token exact (same as _tokenize).
        Fallback: stemmed exact + fuzzy + prefix wildcard.
        """
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
        tokens = cleaned.split()
        primary: list[str] = []
        fallback: list[str] = []
        for t in tokens:
            t_lower = t.lower()
            if t_lower in STOP_WORDS:
                continue
            primary.append(t_lower)
            stemmed = ps.stemWord(t_lower)
            if stemmed != t_lower:
                fallback.append(stemmed)
            if len(t_lower) > 4:
                fallback.append(f"{t_lower}~1")
                fallback.append(f"{stemmed}*")
        return primary, fallback

    def search(self, query: str, limit: int = 20) -> list[tuple[str, float]]:
        """Pure FTS5 search on original (non-stemmed) tokens."""
        tokens = self._tokenize(query)
        if not tokens:
            return []

        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            try:
                session_scores: dict[str, float] = {}
                for token in tokens:
                    try:
                        cursor = conn.execute("""
                            SELECT o.id, o.session_id, o.raw_content,
                                   bm25(observations_fts) as score
                            FROM observations_fts f
                            JOIN observations o ON f.rowid = o.rowid
                            WHERE observations_fts MATCH ?
                            ORDER BY score
                            LIMIT ?
                        """, (token, limit * 3))
                    except sqlite3.OperationalError:
                        continue
                    for row in cursor.fetchall():
                        obs_id, session_id, content, score = row
                        if session_id not in session_scores:
                            session_scores[session_id] = score
                        elif score < session_scores[session_id]:
                            session_scores[session_id] = score
            finally:
                conn.close()

        sorted_sessions = sorted(session_scores.items(), key=lambda x: x[1])
        return [(sid, score) for sid, score in sorted_sessions[:limit]]

    def expand_search(self, query: str, limit: int = 20) -> list[tuple[str, float]]:
        """FTS5 with primary exact + stemming/fuzzy/prefix fallback.

        Used by hybrid_search when the primary token search returns fewer than
        `limit` sessions.
        """
        primary, fallback = self._expand_query(query)
        if not primary:
            return []

        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            try:
                session_scores: dict[str, float] = {}

                def run_frags(frags: list[str]) -> None:
                    for fragment in frags:
                        try:
                            cursor = conn.execute("""
                                SELECT o.id, o.session_id, o.raw_content,
                                       bm25(observations_fts) as score
                                FROM observations_fts f
                                JOIN observations o ON f.rowid = o.rowid
                                WHERE observations_fts MATCH ?
                                ORDER BY score
                                LIMIT ?
                            """, (fragment, limit * 3))
                        except sqlite3.OperationalError:
                            continue
                        for row in cursor.fetchall():
                            obs_id, session_id, content, score = row
                            if session_id not in session_scores:
                                session_scores[session_id] = score
                            elif score < session_scores[session_id]:
                                session_scores[session_id] = score

                run_frags(primary)
                if len(session_scores) < limit:
                    run_frags(fallback)
            finally:
                conn.close()

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


class RealHybridSearch:
    """Wraps the real HybridSearchLayer for benchmark use.

    The HybridSearchLayer is created once per process (embedding model loaded once).
    Each question gets its own SQLite file, but the layer is reused.
    """

    def __init__(self):
        from harness_mem.search import HybridSearchLayer
        from harness_mem.storage.sqlite_index import SQLiteIndex
        index = SQLiteIndex(Path(":memory:"))  # placeholder; path set per-question in set_path
        self._layer = HybridSearchLayer(index)
        self._current_path = ":memory:"

    def set_path(self, db_path: str) -> None:
        """Switch to a different SQLite file (one per question)."""
        if db_path == self._current_path:
            return
        self.close()
        self._current_path = db_path
        from harness_mem.storage.sqlite_index import SQLiteIndex
        self._layer._sqlite = SQLiteIndex(Path(db_path))

    def close(self) -> None:
        self._layer._sqlite.close()
        self._current_path = ""

    def search(
        self,
        query: str,
        limit: int = 20,
        variant: str = "hybrid",
    ) -> list[tuple[str, float]]:
        """Run one benchmark retrieval variant against the real search layer."""
        result = self.search_result(query, limit=limit, variant=variant)
        score_key = "_vec_sim" if variant == "vector" else "_score"
        return [
            (row["session_id"], row.get(score_key, row.get("_score", 0.0)))
            for row in result.rows
        ]

    def search_result(
        self,
        query: str,
        limit: int = 20,
        variant: str = "hybrid",
    ):
        """Return the underlying SearchResult for diagnostic tooling."""
        if variant == "vector":
            return self._layer.search_vector(
                query,
                table="observations",
                limit=limit,
            )
        mode = "fts" if variant == "fts" else "hybrid"
        return self._layer.search(
            query,
            table="observations",
            limit=limit,
            mode=mode,
        )


# =============================================================================
# BENCHMARK RUNNER
# =============================================================================


def run_benchmark(
    data_path: str,
    mode: str = "raw",
    limit: int = 0,
    top_k: int = 5,
    out_file: str | None = None,
    use_real_hybrid: bool = False,
) -> float:
    print(f"\n{'=' * 60}")
    print("  harness-mem × LongMemEval Benchmark")
    print(f"{'=' * 60}")
    print(f"  Data:        {Path(data_path).name}")
    print(f"  Mode:        {mode}")
    print(f"  Real hybrid: {use_real_hybrid}")
    print(f"  Top-K:       {top_k}")
    print(f"  Limit:       {limit or 'all'}")
    print(f"{'─' * 60}\n")

    # Load JSON
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    if limit > 0:
        data = data[:limit]

    _validate_question_types(data)

    all_recall = []
    per_type: dict[str, list[float]] = defaultdict(list)
    results_log = []
    start_time = datetime.now()
    _real_hybrid = RealHybridSearch() if use_real_hybrid else None

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
            doc = _session_doc_for_query(session, question)
            if doc:
                corpus_ids.append(sess_id)
                corpus_texts.append(doc)
                corpus_dates[sess_id] = date

        if not corpus_ids:
            continue

        # Create temp backend for this question
        tmpdir = tempfile.mkdtemp(prefix="hm_lme_")
        store = None
        try:
            db_path = os.path.join(tmpdir, "bench.sqlite")
            store = BenchVerbatimStore(db_path, persist_vectors=use_real_hybrid)

            # Ingest all sessions as Observations
            for sess_id, text in zip(corpus_ids, corpus_texts):
                obs_id = str(uuid4())
                timestamp = corpus_dates.get(sess_id, datetime.now().isoformat())
                store.add(obs_id, sess_id, text, timestamp)

            # Search
            if mode == "raw":
                raw_results = store.search(question, limit=top_k)
                retrieved_ids = [sid for sid, _ in raw_results]
            elif use_real_hybrid:
                assert _real_hybrid is not None
                _real_hybrid.set_path(db_path)
                hybrid_results = _real_hybrid.search(
                    question,
                    limit=top_k,
                )
                retrieved_ids = [sid for sid, _ in hybrid_results]
            else:  # hybrid (synthetic)
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
            if store is not None:
                store.close()
            if _real_hybrid is not None:
                _real_hybrid.close()
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
        output_path = Path(out_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "mode": mode,
                "use_real_hybrid": use_real_hybrid,
                "top_k": top_k,
                "total_questions": len(data),
                "avg_recall": avg_recall,
                "per_type": {k: sum(v) / len(v) for k, v in per_type.items()},
                "results": results_log,
            }, f, indent=2)
        print(f"  Results saved to: {output_path}")

    return avg_recall


def default_output_path(
    mode: str,
    top_k: int,
    now: datetime | None = None,
) -> Path:
    """Return the default output path for benchmark results."""
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M")
    tag = f"_{mode}" if mode != "raw" else ""
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "benchmarks" / "results" / f"results_harness{tag}_top{top_k}_{timestamp}.json"


def _load_result_summary(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "avg_recall": data.get("avg_recall", 0.0),
        "per_type": data.get("per_type", {}),
        "total_questions": data.get("total_questions", 0),
    }


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return default
    return default



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
    parser.add_argument("--use-real-hybrid", action="store_true",
                        help="Use real HybridSearchLayer (FTS+vector via RRF) instead of synthetic hybrid")
    args = parser.parse_args()

    if not args.out:
        args.out = str(default_output_path(
            args.mode,
            args.top_k,
        ))

    run_benchmark(
        args.data_file,
        args.mode,
        args.limit,
        args.top_k,
        args.out,
        args.use_real_hybrid,
    )


if __name__ == "__main__":
    main()
