from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _doc(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_evidence_hardening_track_is_future_only_in_status_and_roadmap() -> None:
    roadmap_status = _doc("docs/roadmap-status.md")
    roadmap_v40 = _doc("docs/roadmap-v40.md")

    assert "## 规划中的后续：Evidence Hardening Track" in roadmap_status
    assert "## v4.6-v5.0：Evidence Hardening Track（规划中）" in roadmap_v40
    assert "| v4.6 Cost / Token Evidence |" in roadmap_status
    assert "| v4.7 Storage v2 Scale Evidence |" in roadmap_status
    assert "| v4.8 Index Fabric Runtime Evidence |" in roadmap_status
    assert "| v4.9 Rust Native Hot Path Evidence |" in roadmap_status
    assert "| v5.0 Default Change Decision Gate |" in roadmap_status
    assert "v4.6-v5.0 evidence-hardening plan is future-only" in roadmap_v40
    assert "不能写成已发布能力或 public claim" in roadmap_status
    assert "v5.0 是决策门，不是功能堆叠版本" in roadmap_v40


def test_evidence_hardening_track_keeps_claim_boundaries_locked() -> None:
    roadmap_v40 = _doc("docs/roadmap-v40.md")
    benchmark_catalog = _doc("benchmark-suite/BENCHMARKS.md")

    for phrase in [
        "No global token-saving claim",
        "no default canonical store or Storage v2 speedup claim",
        "no Tantivy/LanceDB/ANN readiness claim",
        "no Rust speedup claim without native artifact",
        "no default storage/index/reranker/HyDE change from smoke alone",
    ]:
        assert phrase in benchmark_catalog

    assert "named token sidecars" in roadmap_v40
    assert "10k / 100k / 1M scale evidence" in roadmap_v40
    assert "first lazy load vs warm path" in roadmap_v40
    assert "native vs fallback" in roadmap_v40
    assert "dataset hash、command、hardware、冷/热路径、fallback status、token/cost source" in roadmap_v40
