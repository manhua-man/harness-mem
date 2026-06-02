"""MCP stdout cleanliness for the hardened wake renderer (v2.5.1, Req 8).

The wake renderer emits the Rendered_Wake_Output only through ``print`` /
``sys.stdout``. Under MCP, ``tool_wake`` runs ``cmd_wake_up`` inside
``_run_command_to_payload``, which wraps execution in
``contextlib.redirect_stdout(io.StringIO())`` and returns the captured text as
``payload["output"]``. This test pins the three guarantees of Requirement 8:

* 8.1 — the rendered text is returned through the captured output channel
  (``payload["output"]``).
* 8.2 — the real process stdout receives none of the rendered text.
* 8.3 — the returned payload stays JSON-serializable as the tool output.

Data isolation follows project rule P1: a ``LocalMemoryBackend`` is built
against the ``tmp_path``-backed ``data_dir`` fixture (never ``~/.harness-mem/``)
and closed in a ``finally`` block. The backend is injected via the MCP
``set_backend_override`` contract, and ``cmd_wake_up`` reads the same
``tmp_path`` data dir because the autouse ``data_dir`` fixture monkeypatches
``wake.DEFAULT_DATA_DIR`` to it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_mem.core.schemas import ConfirmedRule, MemoryEntry, Skill
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.knowledge_cache import rebuild_wiki_bridge
from harness_mem.mcp.server import set_backend_override, tool_wake
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run

pytestmark = pytest.mark.mcp

PROJECT = "wake-render-stdout-project"


async def _seed(backend: LocalMemoryBackend) -> None:
    """Seed a profile + confirmed rule + accepted entry so wake renders L0/L1.

    Minimal but non-trivial: the profile drives the L0 identity entry, the
    confirmed rule and the accepted current-truth entry drive L1, so the
    rendered text carries real plan-backed content rather than only headers.
    """
    # L0 — project profile (identity entry).
    profile_store = LocalProjectProfileStore(backend.data_dir)
    await profile_store.save(
        ProjectProfile(
            project_name=PROJECT,
            description="Wake renderer hardening stdout test project",
            stacks=["python", "sqlite"],
        )
    )
    # L1 — confirmed rule (current, no valid_to).
    await backend.structured_store.save_confirmed_rule(
        ConfirmedRule(
            project_name=PROJECT,
            pattern="Redirect MCP server stdout to stderr to protect JSON-RPC.",
            trigger="When emitting diagnostics from the MCP server",
            source_candidate_id="candidate-stdout",
        )
    )
    # L1 — accepted current-truth memory entry.
    await backend.structured_store.save_memory_entry(
        MemoryEntry(
            project_name=PROJECT,
            category="architecture",
            content="Wake output is captured and returned as the MCP tool payload.",
            source="manual",
        )
    )
    await backend.structured_store.save_skill(
        Skill(
            project_name=PROJECT,
            name="Release verification workflow",
            activation_condition="When preparing to ship a code change",
            steps=[
                "Run focused tests",
                "Run full pytest",
                "Confirm the working tree is clean",
            ],
            termination_condition="All gates are green",
        )
    )


def test_tool_wake_render_stdout_stays_clean(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Feature: v251-wake-renderer-hardening — MCP stdout cleanliness (Req 8.1, 8.2, 8.3)."""
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    set_backend_override(backend)
    try:
        run(_seed(backend))

        # Drop anything buffered during seeding so the post-call capture only
        # reflects what tool_wake wrote to the real process stdout.
        capsys.readouterr()

        payload = tool_wake(project_name=PROJECT, no_auto_ingest=True)

        captured = capsys.readouterr()

        # Req 8.1 — the rendered text is returned through the captured channel.
        assert payload["success"] is True
        output = payload["output"]
        assert "# Project Profile" in output
        assert "# Essential Truth" in output
        assert "# Active Task" in output
        # Seeded plan-backed content actually surfaced in the rendered L1 text.
        assert "Redirect MCP server stdout to stderr" in output

        # Req 8.2 — the real process stdout received none of the rendered text.
        assert captured.out == ""
        assert "# Project Profile" not in captured.out
        assert "Redirect MCP server stdout to stderr" not in captured.out

        # Req 8.3 — the payload is serializable as the JSON-RPC tool output.
        serialized = json.dumps(payload)
        assert isinstance(serialized, str)
        assert json.loads(serialized)["output"] == output
    finally:
        set_backend_override(None)
        run(backend.close())


def test_tool_wake_compact_renderer_returns_generated_summary(
    data_dir: Path,
    tmp_path: Path,
) -> None:
    """v2.6.3: compact renderer is opt-in and source-attributed."""
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    set_backend_override(backend)
    try:
        project_root = tmp_path / PROJECT
        docs_dir = project_root / "docs"
        docs_dir.mkdir(parents=True)
        (docs_dir / "compact.md").write_text(
            "Compact MCP wake renderer keeps generated claims separate.",
            encoding="utf-8",
        )
        profile = ProjectProfile(
            project_name=PROJECT,
            curated_doc_paths=["docs/compact.md"],
        )
        run(
            rebuild_wiki_bridge(
                backend,
                data_dir=data_dir,
                project_name=PROJECT,
                profile=profile,
                project_root=project_root,
            )
        )

        payload = tool_wake(
            project_name=PROJECT,
            no_auto_ingest=True,
            renderer="compact",
        )

        assert payload["success"] is True
        assert payload["renderer"] == "compact"
        assert "# Compact Wake  (generated summary, not confirmed truth)" in payload["output"]
        assert "Compact MCP wake renderer" in payload["output"]
        assert payload["compact_payload"]["authority"] == "generated_claim"
        assert payload["compact_payload"]["source_ids"]
    finally:
        set_backend_override(None)
        run(backend.close())


def test_tool_wake_opt_in_skill_hints_are_compact_and_default_stays_unchanged(
    data_dir: Path,
) -> None:
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    set_backend_override(backend)
    try:
        run(_seed(backend))

        default_payload = tool_wake(project_name=PROJECT, no_auto_ingest=True)
        hinted_payload = tool_wake(
            project_name=PROJECT,
            no_auto_ingest=True,
            include_skill_hints=True,
            skill_hint_limit=1,
        )

        assert default_payload["success"] is True
        assert "# Skill Hints  (opt-in compact)" not in default_payload["output"]

        assert hinted_payload["success"] is True
        assert "# Skill Hints  (opt-in compact)" in hinted_payload["output"]
        assert "Release verification workflow" in hinted_payload["output"]
        assert "When preparing to ship a code change" in hinted_payload["output"]
        assert "Run focused tests" not in hinted_payload["output"]
        assert "Run full pytest" not in hinted_payload["output"]
        assert "Approx skill-hint tokens:" in hinted_payload["output"]
    finally:
        set_backend_override(None)
        run(backend.close())
