from __future__ import annotations

import json
from pathlib import Path

from harness_mem.adapters.antigravity import AntigravityAdapter


def test_antigravity_reads_real_transcript_shape_and_matches_cwd(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    transcript = root / "brain-id" / ".system_generated" / "logs" / "transcript.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        "\n".join(
            json.dumps(item)
            for item in (
                {
                    "step_index": 0,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "content": "Find the update script",
                },
                {
                    "step_index": 1,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "tool_calls": [
                        {"name": "list_dir", "args": {"Cwd": "F:/repo"}},
                    ],
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )

    adapter = AntigravityAdapter(
        None,
        brain_dir=root,
        project_root=Path("F:/repo"),
    )
    sessions = adapter.list_sessions()

    assert [session["session_id"] for session in sessions] == ["brain-id"]
    observation = adapter.session_to_observation(transcript, "brain-id", "repo")
    assert observation.client == "antigravity"
    assert "Find the update script" in observation.raw_content
    assert "list_dir" in observation.raw_content


def test_antigravity_normalizes_native_workspace_aliases(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    alias_parent = tmp_path / "alias-parent"
    alias_parent.mkdir()
    aliased_workspace = alias_parent / ".." / workspace.name
    brain = tmp_path / "brain"
    transcript = (
        brain
        / "alias-session"
        / ".system_generated"
        / "logs"
        / "transcript.jsonl"
    )
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {
                "step_index": 0,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [
                    {"name": "list_dir", "args": {"Cwd": str(aliased_workspace)}}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    adapter = AntigravityAdapter(None, brain_dir=brain, project_root=workspace)

    assert [session["session_id"] for session in adapter.list_sessions()] == [
        "alias-session"
    ]
