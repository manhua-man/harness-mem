"""Embedding model shootout tool for v1.6.2.

Runs LongMemEval benchmark against all supported embedding models,
compares results against v1.6.0 baseline, and recommends the best model
based on predefined decision rules.

Usage:
    python -m harness_mem.tools.embedding_shootout [--output PATH] [--baseline PATH]
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

# Six-dimension R@5 scores (LongMemEval question_type)
class BenchmarkResult(NamedTuple):
    model_id: str
    knowledge_update: float
    multi_session: float
    single_session_assistant: float
    single_session_preference: float
    single_session_user: float
    temporal_reasoning: float

    def to_dict(self) -> dict[str, float]:
        return {
            "knowledge-update": self.knowledge_update,
            "multi-session": self.multi_session,
            "single-session-assistant": self.single_session_assistant,
            "single-session-preference": self.single_session_preference,
            "single-session-user": self.single_session_user,
            "temporal-reasoning": self.temporal_reasoning,
        }


class BaselineScores(NamedTuple):
    knowledge_update: float
    multi_session: float
    single_session_assistant: float
    single_session_preference: float
    single_session_user: float
    temporal_reasoning: float


def resolve_dataset_path() -> Path | None:
    """Locate the LongMemEval dataset on the local machine.

    Priority:
    1. ``LONGMEMEVAL_DATASET`` env var
    2. repo-local benchmark data
    3. Windows temp paths used by the existing benchmark artifacts
    4. ``/tmp`` fallback for POSIX shells
    """
    env_path = os.environ.get("LONGMEMEVAL_DATASET")
    candidates = []
    if env_path:
        candidates.append(Path(env_path))

    repo_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            repo_root / "benchmarks" / "data" / "longmemeval_s_cleaned.json",
            Path(tempfile.gettempdir()) / "longmemeval_s_cleaned.json",
            Path(tempfile.gettempdir()) / "longmemeval-data" / "longmemeval_s_cleaned.json",
            Path("/tmp/longmemeval_s_cleaned.json"),
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_baseline(baseline_path: Path) -> BaselineScores:
    """Load v1.6.0 baseline scores from markdown file.

    Expected format in the file (from v160-baseline.md):
    | Question Type | n | fts | hybrid (synthetic) | hybrid (real) |
    | `knowledge-update` | 78 | 0.962 | 0.942 | **1.000** |
    | `multi-session` | 133 | 0.792 | 0.781 | **0.923** |
    ...
    """
    if not baseline_path.exists():
        # Fallback to hardcoded v1.6.0 baseline from v160-baseline.md
        return BaselineScores(
            knowledge_update=1.000,
            multi_session=0.923,
            single_session_assistant=0.982,
            single_session_preference=0.967,
            single_session_user=1.000,
            temporal_reasoning=0.915,
        )

    content = baseline_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Parse the "hybrid (real)" column from the table
    scores = {}
    for line in lines:
        line = line.strip()
        if not line.startswith("|") or "Question Type" in line or "---" in line:
            continue

        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue

        # Extract question type (remove backticks and **bold**)
        qtype = parts[1].replace("`", "").replace("*", "").strip()
        if not qtype or qtype == "Question Type":
            continue

        # Extract hybrid (real) score (last column, remove **bold**)
        try:
            score_str = parts[-2].replace("*", "").strip()
            score = float(score_str)
            scores[qtype] = score
        except (ValueError, IndexError):
            continue

    # Map to BaselineScores
    return BaselineScores(
        knowledge_update=scores.get("knowledge-update", 1.000),
        multi_session=scores.get("multi-session", 0.923),
        single_session_assistant=scores.get("single-session-assistant", 0.982),
        single_session_preference=scores.get("single-session-preference", 0.967),
        single_session_user=scores.get("single-session-user", 1.000),
        temporal_reasoning=scores.get("temporal-reasoning", 0.915),
    )


def run_benchmark(model_id: str, progress_prefix: str = "") -> BenchmarkResult:
    """Run LongMemEval for a single model and return six-dimension R@5 scores.

    Args:
        model_id: Embedding model identifier
        progress_prefix: Optional prefix for progress messages (e.g., "[1/3]")
    """
    from harness_mem.tools.longmemeval import run_benchmark as run_longmemeval
    from pathlib import Path
    import tempfile
    import json

    print(f"\n{'=' * 60}")
    print(f"{progress_prefix} Running benchmark for {model_id}...")
    print(f"{'=' * 60}\n")

    # Find dataset
    dataset_path = resolve_dataset_path()

    if not dataset_path:
        print("ERROR: LongMemEval dataset not found. Tried:")
        env_path = os.environ.get("LONGMEMEVAL_DATASET")
        if env_path:
            print(f"  - {env_path}")
        repo_root = Path(__file__).resolve().parents[2]
        for candidate in [
            repo_root / "benchmarks" / "data" / "longmemeval_s_cleaned.json",
            Path(tempfile.gettempdir()) / "longmemeval_s_cleaned.json",
            Path(tempfile.gettempdir()) / "longmemeval-data" / "longmemeval_s_cleaned.json",
            Path("/tmp/longmemeval_s_cleaned.json"),
        ]:
            print(f"  - {candidate}")
        print("\nReturning zero scores.")
        return BenchmarkResult(
            model_id=model_id,
            knowledge_update=0.0,
            multi_session=0.0,
            single_session_assistant=0.0,
            single_session_preference=0.0,
            single_session_user=0.0,
            temporal_reasoning=0.0,
        )

    # Set embedding model for this run
    from harness_mem.embedding import get_model_loader

    # Force load the target model
    print(f"Loading embedding model: {model_id}")
    loader = get_model_loader(model_id)
    loader._ensure_loaded()
    print("Model loaded. Starting evaluation on 500 questions...\n")

    # Run benchmark with real hybrid mode
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        out_path = f.name

    previous_model_id = os.environ.get("HARNESS_MEM_EMBEDDING_MODEL_ID")
    os.environ["HARNESS_MEM_EMBEDDING_MODEL_ID"] = model_id
    try:
        run_longmemeval(
            data_path=str(dataset_path),
            mode="hybrid",
            limit=0,  # all questions
            top_k=5,
            out_file=out_path,
            use_real_hybrid=True,
        )

        # Parse results
        with open(out_path, encoding="utf-8") as f:
            results = json.load(f)

        per_type = results.get("per_type", {})

        result = BenchmarkResult(
            model_id=model_id,
            knowledge_update=per_type.get("knowledge-update", 0.0),
            multi_session=per_type.get("multi-session", 0.0),
            single_session_assistant=per_type.get("single-session-assistant", 0.0),
            single_session_preference=per_type.get("single-session-preference", 0.0),
            single_session_user=per_type.get("single-session-user", 0.0),
            temporal_reasoning=per_type.get("temporal-reasoning", 0.0),
        )

        print(f"\n{progress_prefix} Completed {model_id}")
        print(f"  Avg R@5: {results.get('avg_recall', 0.0):.3f}")

        return result
    finally:
        if previous_model_id is None:
            os.environ.pop("HARNESS_MEM_EMBEDDING_MODEL_ID", None)
        else:
            os.environ["HARNESS_MEM_EMBEDDING_MODEL_ID"] = previous_model_id
        Path(out_path).unlink(missing_ok=True)


def apply_decision_rules(
    results: list[BenchmarkResult],
    baseline: BaselineScores,
) -> tuple[str, str]:
    """Apply decision rules to select the best model.

    Returns:
        (selected_model_id, reason)

    Decision rules (in priority order):
    1. All 6 dims ≥ baseline AND ≥2 dims +1pp
    2. ≥4 dims ≥ baseline AND ≥1 dim +2pp
    3. Fallback to all-MiniLM-L6-v2

    Tiebreaker: bge-small > nomic-embed > all-MiniLM
    """
    baseline_dict = baseline._asdict()
    tiebreaker_priority = ["bge-small-en-v1.5", "nomic-embed-text-v1.5", "all-MiniLM-L6-v2"]

    # Rule 1: All 6 dims ≥ baseline AND ≥2 dims +1pp
    rule1_candidates = []
    for result in results:
        scores = result.to_dict()
        # Map baseline keys (underscore) to score keys (hyphen)
        baseline_mapped = {
            "knowledge-update": baseline_dict["knowledge_update"],
            "multi-session": baseline_dict["multi_session"],
            "single-session-assistant": baseline_dict["single_session_assistant"],
            "single-session-preference": baseline_dict["single_session_preference"],
            "single-session-user": baseline_dict["single_session_user"],
            "temporal-reasoning": baseline_dict["temporal_reasoning"],
        }
        dims_gte_baseline = sum(
            scores[dim] >= baseline_mapped[dim] for dim in scores
        )
        dims_plus_1pp = sum(
            scores[dim] >= baseline_mapped[dim] + 0.01 for dim in scores
        )
        if dims_gte_baseline == 6 and dims_plus_1pp >= 2:
            rule1_candidates.append(result.model_id)

    if rule1_candidates:
        for model in tiebreaker_priority:
            if model in rule1_candidates:
                return model, "Rule 1: all 6 dims ≥ baseline + ≥2 dims +1pp"

    # Rule 2: ≥4 dims ≥ baseline AND ≥1 dim +2pp
    rule2_candidates = []
    for result in results:
        scores = result.to_dict()
        baseline_mapped = {
            "knowledge-update": baseline_dict["knowledge_update"],
            "multi-session": baseline_dict["multi_session"],
            "single-session-assistant": baseline_dict["single_session_assistant"],
            "single-session-preference": baseline_dict["single_session_preference"],
            "single-session-user": baseline_dict["single_session_user"],
            "temporal-reasoning": baseline_dict["temporal_reasoning"],
        }
        dims_gte_baseline = sum(
            scores[dim] >= baseline_mapped[dim] for dim in scores
        )
        dims_plus_2pp = sum(
            scores[dim] >= baseline_mapped[dim] + 0.02 for dim in scores
        )
        if dims_gte_baseline >= 4 and dims_plus_2pp >= 1:
            rule2_candidates.append(result.model_id)

    if rule2_candidates:
        for model in tiebreaker_priority:
            if model in rule2_candidates:
                return model, "Rule 2: ≥4 dims ≥ baseline + ≥1 dim +2pp"

    # Rule 3: Fallback
    return "all-MiniLM-L6-v2", "Rule 3: fallback (no model met rules 1 or 2)"


def generate_report(
    results: list[BenchmarkResult],
    baseline: BaselineScores,
    selected_model: str,
    reason: str,
    output_path: Path,
) -> None:
    """Generate markdown report with benchmark results and recommendation."""
    baseline_dict = baseline._asdict()

    lines = [
        "# Embedding Model Shootout (v1.6.2)",
        "",
        "## Baseline (v1.6.0 hybrid real)",
        "",
        "| Question Type | R@5 |",
        "|---------------|-----|",
        f"| knowledge-update | {baseline.knowledge_update:.3f} |",
        f"| multi-session | {baseline.multi_session:.3f} |",
        f"| single-session-assistant | {baseline.single_session_assistant:.3f} |",
        f"| single-session-preference | {baseline.single_session_preference:.3f} |",
        f"| single-session-user | {baseline.single_session_user:.3f} |",
        f"| temporal-reasoning | {baseline.temporal_reasoning:.3f} |",
        "",
        "## Results",
        "",
        "| Model | knowledge-update | multi-session | single-session-assistant | single-session-preference | single-session-user | temporal-reasoning |",
        "|-------|------------------|---------------|--------------------------|---------------------------|---------------------|--------------------|",
    ]

    for result in results:
        scores = result.to_dict()
        lines.append(
            f"| {result.model_id} | "
            f"{scores['knowledge-update']:.3f} | "
            f"{scores['multi-session']:.3f} | "
            f"{scores['single-session-assistant']:.3f} | "
            f"{scores['single-session-preference']:.3f} | "
            f"{scores['single-session-user']:.3f} | "
            f"{scores['temporal-reasoning']:.3f} |"
        )

    lines.extend([
        "",
        "## Delta from Baseline",
        "",
        "| Model | knowledge-update | multi-session | single-session-assistant | single-session-preference | single-session-user | temporal-reasoning |",
        "|-------|------------------|---------------|--------------------------|---------------------------|---------------------|--------------------|",
    ])

    for result in results:
        scores = result.to_dict()
        deltas = {dim: scores[dim] - baseline_dict[dim.replace("-", "_")] for dim in scores}
        lines.append(
            f"| {result.model_id} | "
            f"{deltas['knowledge-update']:+.3f} | "
            f"{deltas['multi-session']:+.3f} | "
            f"{deltas['single-session-assistant']:+.3f} | "
            f"{deltas['single-session-preference']:+.3f} | "
            f"{deltas['single-session-user']:+.3f} | "
            f"{deltas['temporal-reasoning']:+.3f} |"
        )

    lines.extend([
        "",
        "## Decision",
        "",
        f"**Selected model:** `{selected_model}`",
        "",
        f"**Reason:** {reason}",
        "",
        "## Decision Rules",
        "",
        "1. All 6 dims ≥ baseline AND ≥2 dims +1pp (≥0.010)",
        "2. ≥4 dims ≥ baseline AND ≥1 dim +2pp (≥0.020)",
        "3. Fallback to all-MiniLM-L6-v2",
        "",
        "Tiebreaker priority: bge-small-en-v1.5 > nomic-embed-text-v1.5 > all-MiniLM-L6-v2",
    ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReport written to: {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run embedding model shootout and generate recommendation"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/benchmark/v162-embedding-shootout.md"),
        help="Output path for report (default: docs/benchmark/v162-embedding-shootout.md)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("docs/benchmark/v160-baseline.md"),
        help="Baseline scores file (default: docs/benchmark/v160-baseline.md)",
    )
    args = parser.parse_args()

    # Load baseline
    baseline = load_baseline(args.baseline)
    print(f"Loaded baseline from {args.baseline}")
    print("Baseline scores:")
    print(f"  knowledge-update: {baseline.knowledge_update:.3f}")
    print(f"  multi-session: {baseline.multi_session:.3f}")
    print(f"  single-session-assistant: {baseline.single_session_assistant:.3f}")
    print(f"  single-session-preference: {baseline.single_session_preference:.3f}")
    print(f"  single-session-user: {baseline.single_session_user:.3f}")
    print(f"  temporal-reasoning: {baseline.temporal_reasoning:.3f}")

    # Run benchmarks for all supported models
    from harness_mem.embedding.model_registry import SUPPORTED_MODELS

    results = []
    total_models = len(SUPPORTED_MODELS)
    for idx, model_id in enumerate(SUPPORTED_MODELS, start=1):
        progress_prefix = f"[{idx}/{total_models}]"
        result = run_benchmark(model_id, progress_prefix=progress_prefix)
        results.append(result)

    # Apply decision rules
    selected_model, reason = apply_decision_rules(results, baseline)

    # Generate report
    generate_report(results, baseline, selected_model, reason, args.output)

    print("\n✓ Shootout complete")
    print(f"  Selected model: {selected_model}")
    print(f"  Reason: {reason}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
