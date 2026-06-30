from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from harness_mem.integration.installer import install_hook


def _install_template(tmp_path: Path, template_name: str) -> str:
    target = tmp_path / template_name.replace(".template", "")
    written = install_hook(
        template_name=template_name,
        target_path=target,
        project_root=tmp_path,
        force=False,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        doc_pointer="docs/quickstart.md",
    )
    return written.read_text(encoding="utf-8")


def test_dream_end_hook_templates_use_explicit_action(tmp_path: Path) -> None:
    for template in ("cursor_after_agent.sh.template", "claude_code_hook.sh.template"):
        body = _install_template(tmp_path, template)

        assert "python -m harness_mem.host_entry" in body
        assert "--action post-turn-maintenance" in body
        assert "--session-ids" not in body
        assert "triggers.after_agent" not in body
        assert "reflection" not in body.lower()
        assert "metabolism" not in body.lower()
        assert ">/dev/null 2>&1" in body
        if template == "cursor_after_agent.sh.template":
            assert "install-cursor-suite" in body
        else:
            assert "install-claude-suite" in body


def test_wake_start_hook_templates_keep_stdout_for_injection(tmp_path: Path) -> None:
    for template in (
        "cursor_session_start.sh.template",
        "claude_code_session_start.sh.template",
    ):
        body = _install_template(tmp_path, template)

        assert "python -m harness_mem.host_entry" in body
        assert "--action wake-start" in body
        assert "triggers.after_agent" not in body
        assert "reflection" not in body.lower()
        assert "metabolism" not in body.lower()
        assert ">/dev/null 2>&1" not in body
        assert "2>/dev/null" in body


def test_hook_suite_installer_creates_cursor_and_claude_suites(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from harness_mem.integration.installer import (
        HookSpec,
        install_hook_suite,
    )

    cursor_specs = (
        HookSpec("cursor_session_start.sh.template", tmp_path / ".cursor" / "hooks" / "session-start.sh"),
        HookSpec("cursor_after_agent.sh.template", tmp_path / ".cursor" / "hooks" / "after-agent.sh"),
    )
    results = install_hook_suite(
        specs=cursor_specs,
        project_root=tmp_path,
        force=False,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert [result.status for result in results] == ["installed", "installed"]
    assert results[0].target_path.exists()
    assert results[1].target_path.exists()
    assert "--action wake-start" in results[0].target_path.read_text(encoding="utf-8")
    assert "--action post-turn-maintenance" in results[1].target_path.read_text(encoding="utf-8")


def test_hook_suite_installer_is_idempotent(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from harness_mem.integration.installer import HookSpec, install_hook_suite

    specs = (
        HookSpec("cursor_session_start.sh.template", tmp_path / ".cursor" / "hooks" / "session-start.sh"),
        HookSpec("cursor_after_agent.sh.template", tmp_path / ".cursor" / "hooks" / "after-agent.sh"),
    )
    first = install_hook_suite(
        specs=specs,
        project_root=tmp_path,
        force=False,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = install_hook_suite(
        specs=specs,
        project_root=tmp_path,
        force=False,
        harness_mem_version="test",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert [item.status for item in first] == ["installed", "installed"]
    assert [item.status for item in second] == ["exists", "exists"]
