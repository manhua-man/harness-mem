from __future__ import annotations

from pathlib import Path

from harness_mem.config.merge import _RECOGNIZED_KEYS


REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_worker_mode_docs_match_runtime_truth() -> None:
    worker_row = next(
        row for row in _RECOGNIZED_KEYS if row[0] == "worker.mode"
    )
    assert worker_row[2] == ("off", "on")

    cli_doc = _text("docs/cli/v2.4.md")
    roadmap_v24 = _text("docs/roadmap-v24.md")
    roadmap_status = _text("docs/roadmap-status.md")

    assert "| `worker.mode` | `off`, `on` | `off` |" in cli_doc
    assert "`off` \\| `on`" in roadmap_v24
    assert "`worker.mode=daemon`" not in roadmap_v24
    assert "`worker.mode=daemon`" not in roadmap_status


def test_scheduler_trigger_docs_match_runtime_truth() -> None:
    scheduler_row = next(
        row for row in _RECOGNIZED_KEYS if row[0] == "triggers.scheduler"
    )
    assert scheduler_row[2] == ("off", "on")

    cli_doc = _text("docs/cli/v2.4.md")
    roadmap_v24 = _text("docs/roadmap-v24.md")
    roadmap_status = _text("docs/roadmap-status.md")

    assert "| `triggers.scheduler` | `off`, `on` | `off` |" in cli_doc
    assert "`off` \\| `on`" in roadmap_v24
    assert "`off` \\| `cron`" not in roadmap_v24
    assert "`triggers.scheduler=cron`" not in roadmap_status


def test_distill_mode_docs_match_runtime_truth() -> None:
    distill_row = next(
        row for row in _RECOGNIZED_KEYS if row[0] == "distill.mode"
    )
    assert distill_row[2] == ("defer_to_agent", "inline", "worker")

    cli_doc = _text("docs/cli/v2.4.md")
    roadmap_v24 = _text("docs/roadmap-v24.md")
    roadmap_status = _text("docs/roadmap-status.md")

    assert "| `distill.mode` | `defer_to_agent`, `inline`, `worker` | `defer_to_agent` |" in cli_doc
    assert "`notify_only`" not in roadmap_v24
    assert "`embedded_llm`" not in roadmap_v24
    assert "`notify_only`" not in roadmap_status
    assert "`embedded_llm`" not in roadmap_status
