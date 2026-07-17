from __future__ import annotations

from pathlib import Path


def test_governance_handlers_stay_out_of_main_handler_module() -> None:
    root = Path(__file__).resolve().parents[1]
    main = (root / "harness_mem" / "mcp" / "tool_handlers.py").read_text(
        encoding="utf-8"
    )
    governance = (
        root / "harness_mem" / "mcp" / "governance_handlers.py"
    ).read_text(encoding="utf-8")

    assert len(main.splitlines()) < 3_500
    assert "def tool_govern_memory(" not in main
    assert "def tool_suggest_memory_entry(" not in main
    assert "def tool_govern_memory(" in governance
    assert "def tool_suggest_memory_entry(" in governance
    assert "from harness_mem.mcp.governance_handlers import (" in main
