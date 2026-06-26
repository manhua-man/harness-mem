"""PRD/product-doc sync handler for session-distill."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

EnsureDirs = Callable[[], None]
LoadManifest = Callable[[], dict[str, Any]]

PRD_KEYWORDS = (
    "prd",
    "roadmap",
    "launch",
    "v1",
    "feature",
    "architecture",
    "decision",
    "milestone",
    "scope",
    "requirement",
    "product",
)


def prd_related_sessions(
    sessions: list[dict[str, Any]],
    *,
    keywords: tuple[str, ...] = PRD_KEYWORDS,
) -> list[dict[str, Any]]:
    candidates = []
    for session in sessions:
        if not session.get("bundle_path"):
            continue
        bundle_path = Path(session["bundle_path"])
        if not bundle_path.exists():
            continue

        content = bundle_path.read_text(encoding="utf-8").lower()
        if any(keyword in content for keyword in keywords):
            candidates.append(session)
    return candidates


def render_prd_sync_candidate(
    *,
    candidates: list[dict[str, Any]],
    today: str,
    keywords: tuple[str, ...] = PRD_KEYWORDS,
) -> str:
    lines = [
        f"# PRD Sync Candidate - {today}",
        "",
        "> Candidate only. Review before editing canonical PRD or roadmap docs.",
        "",
        "## Source Packets",
        "",
    ]
    for session in candidates:
        lines.append(f"- `{session['session_id']}`")

    lines.extend(["", "## Detected Topics", "", "*(Auto-detected from packet content)*", ""])
    detected = set()
    for session in candidates:
        if session.get("bundle_path"):
            content = Path(session["bundle_path"]).read_text(encoding="utf-8")
            for keyword in keywords:
                if keyword in content.lower():
                    detected.add(keyword)
    for keyword in sorted(detected):
        lines.append(f"- {keyword}")

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This note is generated from bundled session-distill packets.",
            "- It does not update canonical PRD docs, roadmap docs, knowledge-base truth, or confirmed truth by itself.",
            "- Treat it as a review artifact before any manual product-doc edits.",
            "",
            "## Suggested Decision Records",
            "",
            "*(Placeholder - fill in after review)*",
            "",
            "```markdown",
            "## YYYY-MM-DD - <topic>",
            "- **status**: pending",
            "- **decision**: <summary>",
            "- **source**: <doc>",
            "- **rationale**: <distilled-path>",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def cmd_prd_sync(
    *,
    dry_run: bool = True,
    ensure_dirs: EnsureDirs,
    load_manifest: LoadManifest,
    prd_distilled_dir: Path,
) -> int:
    """Generate PRD sync candidates from bundled packets."""

    print("==> PRD Sync: Generating candidates from bundled packets")
    print(f"    Dry-run: {dry_run}")
    print("")

    ensure_dirs()
    manifest = load_manifest()
    bundled = [s for s in manifest["sessions"] if s["status"] == "bundled"]

    if not bundled:
        print("  No bundled packets found. Run /hm:distill first.")
        return 0

    candidates = prd_related_sessions(bundled)

    if not candidates:
        print("  No PRD-related packets found.")
        return 0

    print(f"  Found {len(candidates)} PRD-related packet(s):")
    for session in candidates:
        print(f"    - {session['session_id']}")

    today = datetime.now().strftime("%Y-%m-%d")
    distilled_path = prd_distilled_dir / f"{today}-prd-sync-candidate.md"
    rendered = render_prd_sync_candidate(candidates=candidates, today=today)

    if not dry_run:
        prd_distilled_dir.mkdir(parents=True, exist_ok=True)
        distilled_path.write_text(rendered, encoding="utf-8")
        print(f"  -> Generated candidate: {distilled_path}")
        print("  -> No canonical PRD/roadmap docs were modified.")
    else:
        print("  [DRY-RUN] No files written. Use --apply to confirm.")
        print("  [DRY-RUN] Candidate preview only; canonical PRD/roadmap docs remain unchanged.")
    return 0
