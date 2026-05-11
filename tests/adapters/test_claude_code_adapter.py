from __future__ import annotations

import json
from pathlib import Path

from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter


def test_observation_summary_keeps_recent_tail_turns(tmp_path: Path):
    session_path = tmp_path / "sess-long.jsonl"
    records = []
    for index in range(1, 26):
        records.append({
            "type": "user",
            "message": {"content": f"Request {index}: inspect the project."},
        })
        records.append({
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Final Unity finding: PrefabFactory owns scene generation."
                            if index == 25
                            else f"Interim note {index}: still inspecting files."
                        ),
                    }
                ],
            },
        })
    session_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    adapter = ClaudeCodeAdapter(None, sessions_dir=tmp_path)
    observation = adapter.session_to_observation(session_path, "sess-long", "unity-project")

    assert "## Turn 1" in observation.raw_content
    assert "## Turn 25" in observation.raw_content
    assert "PrefabFactory owns scene generation" in observation.raw_content
    assert "middle turns omitted" in observation.raw_content
    assert "## Turn 11" not in observation.raw_content
