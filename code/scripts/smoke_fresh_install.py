"""Exercise the installed Agent capabilities with an empty workspace and home."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def verify_installed(expected_version: str) -> None:
    """Run in a new interpreter with the installed wheel as the import target."""
    from importlib.metadata import distribution
    from importlib.util import find_spec

    from harness_mem import __version__
    from harness_mem.distill import Distill
    from harness_mem.search import search
    from harness_mem.transcript_chunking import transcript_bytes_revision

    pkg = distribution("harness-mem")
    if __version__ != expected_version or pkg.version != expected_version:
        raise RuntimeError(f"Expected installed version {expected_version}, got {pkg.version}")
    scripts = {entry.name for entry in pkg.entry_points if entry.group == "console_scripts"}
    if scripts != {"harness-mem-hook"} or find_spec("harness_mem.mcp.server") is not None:
        raise RuntimeError(f"Unexpected installed runtime entry points: {scripts}")
    skills = {path.as_posix(): path for path in pkg.files or [] if path.name == "SKILL.md"}
    if set(skills) != {f".agents/skills/{name}/SKILL.md" for name in ("search", "distill")}:
        raise RuntimeError(f"Unexpected packaged skills: {list(skills)}")
    for name, skill in skills.items():
        operation = Path(name).parent.name
        if f"from harness_mem.{operation} import " not in skill.read_text(encoding="utf-8"):
            raise RuntimeError(f"{name} does not describe the installed interface")
    inventory = Distill().sessions(clients=["codex"])
    if not inventory["success"] or inventory.get("sessions") or search("first use")["status"] != "empty":
        raise RuntimeError("Agent entry points are unavailable in the empty workspace")
    if transcript_bytes_revision(b"\xef\xbb\xbfuser:\r\nassistant:\x00\xff\n") != (
        "sha256:ff3a9081f301fcb0a6c45ccedcb26455caefce97d8a46da1cfab7e52b51c72a2"
    ):
        raise RuntimeError("Cross-platform transcript hash mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--verify-installed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    version = args.expected_version.removeprefix("v")
    if args.verify_installed:
        verify_installed(version)
        return 0

    with tempfile.TemporaryDirectory(prefix="harness-mem-first-install-") as temp:
        root = Path(temp)
        home = root / "home"
        workspace = root / "workspace"
        home.mkdir()
        workspace.mkdir()
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
                   CODEX_HOME=str(home / ".codex"), HARNESS_MEM_DATA_DIR=str(root / "data"),
                   HARNESS_MEM_PROJECT_ROOT=str(workspace), HARNESS_MEM_DISABLE_EMBEDDINGS="1")
        subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve()),
             "--expected-version", version, "--verify-installed"],
            cwd=workspace, env=env, check=True, timeout=60,
        )
        if list(workspace.iterdir()) or (home / ".codex").exists():
            raise RuntimeError("First use created workspace or host configuration")
    print(json.dumps({
        "verified": True, "version": version, "platform": sys.platform,
        "distill_available": True, "agent_search_empty": True, "only_hook_callback": True,
        "workspace_untouched": True, "host_config_untouched": True,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
