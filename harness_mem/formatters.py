"""Shared formatters for CLI output — phase, budget, truncation, labels."""

from __future__ import annotations


def format_phase(level: str, next_step: str, why: str) -> str:
    """Format phase/next_step/why block.

    Args:
        level: Phase level (L1-L4+)
        next_step: Recommended command or action
        why: Why this is recommended
    """
    lines = [
        f"📍 Phase: {level}",
        f"   Next: {next_step}",
        f"   Why: {why}",
    ]
    return "\n".join(lines)


def truncate(text: str, max_length: int = 100, marker: str = "[...truncated]") -> str:
    """Truncate text to max_length, appending marker if truncated."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + " " + marker


def format_memory_entry_source(entry) -> str:
    """Get source label for a memory entry."""
    for tag in getattr(entry, "tags", []) or []:
        if tag.startswith("pattern-source:"):
            return tag.split(":", 1)[1]
    return getattr(entry, "category", "unknown")


def format_session_identifier(session: dict) -> str:
    """Extract a displayable session identifier from a session dict."""
    session_id = session.get("session_id")
    if session_id:
        return str(session_id)
    name = session.get("name")
    if name:
        from pathlib import Path
        return Path(str(name)).stem
    return "unknown-session"


def format_session_summary(session: dict) -> str:
    """Format a session summary line."""
    name = session.get("name", "unknown")
    size = session.get("size", "?")
    lines = session.get("lines", 0)
    mtime = session.get("mtime")
    if mtime:
        if hasattr(mtime, "strftime"):
            time_str = mtime.strftime("%Y-%m-%d %H:%M")
        else:
            time_str = str(mtime)[:16]
    else:
        time_str = "?"
    return f"{name}  {size}  {lines} lines  {time_str}"


def format_provenance(prov: dict | None) -> str | None:
    """Format provenance dict as a source hint line."""
    if not prov:
        return None
    src = prov.get("session_id", prov.get("agent_type", "unknown"))
    return f"📍 {src}"


def wake_budget_chars(
    profile_chars: int,
    rules_chars: int,
    entries_chars: int,
    handoffs_chars: int,
) -> tuple[int, str]:
    """Calculate total wake-up budget in characters.

    Returns (total_chars, level) tuple.
    Level thresholds: L1 < 2k, L2 < 5k, L3 < 10k, L4+ >= 10k
    """
    total = profile_chars + rules_chars + entries_chars + handoffs_chars
    if total < 2000:
        return total, "L1"
    elif total < 5000:
        return total, "L2"
    elif total < 10000:
        return total, "L3"
    else:
        return total, "L4+"


def format_wake_budget_line(total_chars: int, level: str) -> str:
    """Format the wake budget summary line."""
    return f"Approx wake-up tokens: ≈ {total_chars:,} [{level}]"
