from __future__ import annotations

import json
from pathlib import Path


def test_plugin_prompts_offer_memory_tasks_without_a_host_command() -> None:
    manifest = json.loads(
        Path("code/plugins/harness-mem/.codex-plugin/plugin.json").read_text(
            encoding="utf-8"
        )
    )
    prompts = manifest["interface"]["defaultPrompt"]
    assert prompts
    assert all(prompt and "$hm" not in prompt and "/hm" not in prompt for prompt in prompts)
    assert manifest["mcpServers"] == "./.mcp.json"


def test_doctor_does_not_publish_retired_weak_link_experiment() -> None:
    doctor = Path("harness_mem/commands/doctor.py").read_text(encoding="utf-8")
    assert "Weak-link signal influence" not in doctor
    assert "experimental skills" not in doctor
    assert "set weak_link_signals=true" not in doctor


def test_retired_terminal_daily_command_modules_are_removed() -> None:
    retired = (
        "candidates.py",
        "handoff.py",
        "profile.py",
        "search.py",
        "status.py",
    )
    for name in retired:
        assert not (Path("harness_mem/commands") / name).exists()
