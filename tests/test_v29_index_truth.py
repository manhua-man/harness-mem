from pathlib import Path


def _read(relative_path: str) -> str:
    return (Path(__file__).resolve().parents[1] / relative_path).read_text(
        encoding="utf-8"
    )


def test_docs_readme_describes_v29_as_release_train() -> None:
    docs_readme = _read("docs/README.md")

    assert (
        "| `roadmap-v29.md` | v2.9 roadmap：PRD sync + maintenance/truth-sync release train |"
        in docs_readme
    )
    assert "| `roadmap-v29.md` | v2.9 roadmap：PRD sync candidate surface |" not in docs_readme


def test_roadmap_status_does_not_reduce_v29_to_prd_sync_only() -> None:
    roadmap_status = _read("docs/roadmap-status.md")

    assert (
        "| v2.9.x | PRD sync 起步，随后扩成 maintenance / triage / truth-sync release train：`/hm:prd-sync`、`/hm:status`、plugin doctor helper、maintenance CLI collateral、reflection/config truth sync、wake/distill/status 入口真值收口 | `docs/roadmap-v29.md` |"
        in roadmap_status
    )
    assert (
        "| v2.9.x | PRD Sync Candidate Surface：`/hm:prd-sync` 默认 dry-run、`--apply` 只写 candidate markdown、不直改 PRD/roadmap | `docs/roadmap-v29.md` |"
        not in roadmap_status
    )
