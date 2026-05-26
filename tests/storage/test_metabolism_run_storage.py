from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.core.schemas import MetabolismRun
from harness_mem.storage.local_structured_store import LocalStructuredStore
from tests.helpers import run

pytestmark = pytest.mark.storage


@pytest.fixture
def store(tmp_path: Path):
    local_store = LocalStructuredStore(tmp_path)
    try:
        yield local_store
    finally:
        local_store.close()


def test_metabolism_run_schema_roundtrip():
    """to_dict / from_dict round-trips field values."""
    started = datetime(2026, 5, 17, 0, 0, tzinfo=timezone.utc)
    completed = datetime(2026, 5, 17, 0, 1, tzinfo=timezone.utc)
    original = MetabolismRun(
        project_name="demo",
        kind="preview",
        started_at=started,
        completed_at=completed,
        status="preview",
        input_window={"time_range": ["2026-05-10T00:00:00+00:00", "2026-05-17T00:00:00+00:00"]},
        selected_signal_ids=["sig-1", "sig-2"],
        output_counts={"suggestions": 0},
        duration_ms=42,
        notes=["truncated_within_observations: 200/847"],
    )

    rebuilt = MetabolismRun.from_dict(original.to_dict())

    assert rebuilt.id == original.id
    assert rebuilt.project_name == "demo"
    assert rebuilt.kind == "preview"
    assert rebuilt.started_at == started
    assert rebuilt.completed_at == completed
    assert rebuilt.status == "preview"
    assert rebuilt.input_window == original.input_window
    assert rebuilt.selected_signal_ids == ["sig-1", "sig-2"]
    assert rebuilt.output_counts == {"suggestions": 0}
    assert rebuilt.duration_ms == 42
    assert rebuilt.notes == ["truncated_within_observations: 200/847"]


def test_metabolism_run_from_dict_defends_against_missing_fields():
    """Older blobs missing newer fields still load with sensible defaults."""
    minimal = {
        "id": "run-001",
        "project_name": "demo",
        "started_at": "2026-05-17T00:00:00+00:00",
    }

    rebuilt = MetabolismRun.from_dict(dict(minimal))

    assert rebuilt.id == "run-001"
    assert rebuilt.project_name == "demo"
    assert rebuilt.kind == "preview"
    assert rebuilt.completed_at is None
    assert rebuilt.status == "preview"
    assert rebuilt.input_window == {}
    assert rebuilt.selected_signal_ids == []
    assert rebuilt.output_counts == {"suggestions": 0}
    assert rebuilt.duration_ms == 0
    assert rebuilt.notes is None


def test_metabolism_run_from_dict_back_compat_old_and_new_output_counts():
    """v2.3.1 task 5.4: ``output_counts`` must round-trip both shapes.

    * v2.3.0 wrote ``{"suggestions": 0}`` (single-key form). ``from_dict``
      must accept it untouched — no silent rewrite to per-type keys.
    * v2.3.1 writes three explicit keys
      (``merge_suggestions / stale_suggestions / supersede_suggestions``).
      ``from_dict`` must round-trip the full dict.
    * Records that drop one of the three new keys reload with
      ``.get(key, 0)`` semantics — readers treat the absent key as 0
      without ``from_dict`` inventing one (we don't want every old blob
      to grow synthetic keys on read).
    """
    base = {
        "id": "run-old-form",
        "project_name": "demo",
        "started_at": "2026-05-17T00:00:00+00:00",
    }

    # 1) Old preview shape from v2.3.0 round-trips verbatim.
    old_form = MetabolismRun.from_dict({**base, "output_counts": {"suggestions": 0}})
    assert old_form.output_counts == {"suggestions": 0}
    # Legacy readers that look for the new keys see 0 via .get().
    assert old_form.output_counts.get("merge_suggestions", 0) == 0
    assert old_form.output_counts.get("stale_suggestions", 0) == 0
    assert old_form.output_counts.get("supersede_suggestions", 0) == 0

    # 2) New v2.3.1 shape with all three keys round-trips.
    new_form = MetabolismRun.from_dict(
        {
            **base,
            "id": "run-new-form",
            "output_counts": {
                "merge_suggestions": 2,
                "stale_suggestions": 1,
                "supersede_suggestions": 0,
            },
        }
    )
    assert new_form.output_counts == {
        "merge_suggestions": 2,
        "stale_suggestions": 1,
        "supersede_suggestions": 0,
    }
    # Legacy ``"suggestions"`` key absent on new records.
    assert "suggestions" not in new_form.output_counts

    # 3) Partial new form (one of the three keys missing) — caller's
    # ``.get(key, 0)`` reads it as 0, ``from_dict`` does not invent the
    # missing key.
    partial = MetabolismRun.from_dict(
        {
            **base,
            "id": "run-partial-form",
            "output_counts": {"merge_suggestions": 3},
        }
    )
    assert partial.output_counts == {"merge_suggestions": 3}
    assert partial.output_counts.get("stale_suggestions", 0) == 0
    assert partial.output_counts.get("supersede_suggestions", 0) == 0


def test_metabolism_run_storage_roundtrip(store: LocalStructuredStore):
    """save_* persists and list_* returns the same record."""
    record = MetabolismRun(
        project_name="demo",
        notes=["truncated_within_observations: 200/300"],
    )

    assert run(store.save_metabolism_run(record)) == record.id

    listed = run(store.list_metabolism_runs("demo"))
    assert [item.id for item in listed] == [record.id]
    assert listed[0].notes == ["truncated_within_observations: 200/300"]


def test_metabolism_run_kind_filter(store: LocalStructuredStore):
    """list_metabolism_runs filters by kind when set."""
    base = datetime.now(timezone.utc)
    preview_a = MetabolismRun(
        project_name="demo",
        kind="preview",
        started_at=base - timedelta(minutes=2),
    )
    preview_b = MetabolismRun(
        project_name="demo",
        kind="preview",
        started_at=base - timedelta(minutes=1),
    )
    metabolism = MetabolismRun(
        project_name="demo",
        kind="metabolism",
        started_at=base,
    )

    for record in (preview_a, preview_b, metabolism):
        run(store.save_metabolism_run(record))

    previews = run(store.list_metabolism_runs("demo", kind="preview"))
    assert {item.id for item in previews} == {preview_a.id, preview_b.id}

    metabolisms = run(store.list_metabolism_runs("demo", kind="metabolism"))
    assert [item.id for item in metabolisms] == [metabolism.id]

    all_runs = run(store.list_metabolism_runs("demo"))
    assert len(all_runs) == 3
    # Newest first by started_at.
    assert all_runs[0].id == metabolism.id


def test_metabolism_run_empty_project_returns_empty_list(store: LocalStructuredStore):
    assert run(store.list_metabolism_runs("nobody")) == []


def test_metabolism_run_preview_shape_round_trip(store: LocalStructuredStore):
    """Lock in the canonical preview run shape: empty-window dimensions,
    `kind="preview"` / `status="preview"`, `output_counts={"suggestions": 0}`,
    and round-trip through both `to_dict / from_dict` and the store.

    Phase 3 boundary: 3.5 only validates the preview SHAPE contract via
    schema + store. It does NOT call `select_replay_window`; the
    selector ↔ store glue is task 4.2 and the integration sequence is 4.4.
    """
    preview_input_window = {
        "time_range": {
            "start": "2026-05-01T00:00:00+00:00",
            "end": "2026-05-31T00:00:00+00:00",
        },
        "dimensions": {
            "observations": {"selected_ids": [], "truncated": False, "total_seen": 0},
            "pending_candidates": {"selected_ids": [], "truncated": False, "total_seen": 0},
            "historical_truths": {"selected_ids": [], "truncated": False, "total_seen": 0},
            "low_success_skills": {"selected_ids": [], "truncated": False, "total_seen": 0},
            "repeat_search_hits": {"selected_ids": [], "truncated": False, "total_seen": 0},
        },
        "signal_ids": [],
        "notes": ["soft_token_budget: 0/16000"],
    }

    started = datetime.now(timezone.utc)
    completed = started + timedelta(milliseconds=5)
    preview_run = MetabolismRun(
        project_name="3-5-preview-project",
        kind="preview",
        status="preview",
        started_at=started,
        completed_at=completed,
        input_window=preview_input_window,
        selected_signal_ids=[],
        output_counts={"suggestions": 0},
        duration_ms=5,
        notes=None,
    )

    # 1) Schema round-trip preserves the preview shape verbatim.
    rebuilt = MetabolismRun.from_dict(preview_run.to_dict())
    assert rebuilt.kind == "preview"
    assert rebuilt.status == "preview"
    assert rebuilt.output_counts == {"suggestions": 0}
    assert rebuilt.selected_signal_ids == []
    assert rebuilt.input_window == preview_input_window
    assert rebuilt.duration_ms == 5

    # 2) Store write/read preserves the same shape.
    assert run(store.save_metabolism_run(preview_run)) == preview_run.id

    listed = run(store.list_metabolism_runs("3-5-preview-project", kind="preview"))
    assert [item.id for item in listed] == [preview_run.id]
    only = listed[0]
    assert only.kind == "preview"
    assert only.status == "preview"
    assert only.output_counts == {"suggestions": 0}
    assert only.input_window == preview_input_window
