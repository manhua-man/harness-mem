"""Focused current-truth guard for maintenance-surface collateral."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_SNIPPETS: dict[str, tuple[str, ...]] = {
    "README.md": (
        "CLI maintenance console (quickstart, doctor, purge, maintenance, import, config, integration)",
    ),
    "openspec/specs/mcp/spec.md": (
        "`init` / `quickstart` / `qs` / `doctor` / `import` / `purge` / `maintenance` / `config` / `integration`",
    ),
    "openspec/specs/telemetry/spec.md": (
        "init / quickstart / qs / doctor / purge / maintenance / import / config / integration",
    ),
    "docs/v2-user-test-packet.md": (
        "`harness-mem quickstart` / `doctor` / `purge` / `maintenance` / `import` / `config` / `integration`",
    ),
}


def test_current_maintenance_surface_is_stated_consistently() -> None:
    for rel_path, snippets in EXPECTED_SNIPPETS.items():
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in text, (
                f"missing current maintenance-surface snippet in {rel_path}: "
                f"{snippet}"
            )
