from __future__ import annotations

from pathlib import Path


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
