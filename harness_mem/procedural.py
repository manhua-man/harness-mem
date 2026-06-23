"""Read-only helpers for procedural memory spike fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from harness_mem.core.schemas.procedural_candidate import ProceduralCandidate


def load_procedural_candidate_fixture(path: Path | str) -> ProceduralCandidate:
    """Load one procedural candidate fixture without writing to runtime stores."""
    fixture_path = Path(path)
    data = json.loads(fixture_path.read_text())
    data.setdefault("source", str(fixture_path))
    return ProceduralCandidate.from_dict(data)


def load_procedural_candidate_fixtures(directory: Path | str) -> list[ProceduralCandidate]:
    """Load all procedural candidate fixtures from a directory in stable order."""
    fixture_dir = Path(directory)
    return [
        load_procedural_candidate_fixture(path)
        for path in sorted(fixture_dir.glob("*.json"))
    ]
