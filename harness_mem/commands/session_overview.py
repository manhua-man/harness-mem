"""Validate coverage and count Agent-proposed themes without writing memory."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from harness_mem.commands.session_inventory import read_session_page


def _covers(ranges: list[tuple[int, int]], start: int, end: int) -> bool:
    frontier = start
    for left, right in sorted(ranges):
        if left > frontier:
            break
        frontier = max(frontier, right)
        if frontier >= end:
            return True
    return start == end


def build_session_overview(
    data_dir: Path, *, project_root: Path | None, project_name: str,
    sessions: list[dict], coverage: list[dict], topics: list[dict],
) -> dict:
    """Themes are Agent judgments; counters and source ranges are checked here."""
    if not sessions:
        raise ValueError("select sessions before requesting a theme overview")
    refs = {item["reference_id"]: item for item in sessions}
    if len(refs) != len(sessions):
        raise ValueError("duplicate session references")
    sources = {
        ref: read_session_page(data_dir, project_root=project_root, project_name=project_name,
                               session=session, offset=0, page_chars=1)
        for ref, session in refs.items()
    }
    ranges: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for page in coverage:
        ref = page.get("reference_id")
        source = sources.get(ref)
        if not isinstance(ref, str) or source is None or page.get("content_sha256") != source["content_sha256"]:
            raise ValueError("overview coverage does not match the selected revision")
        start, end = page.get("offset"), page.get("end")
        if type(start) is not int or type(end) is not int or not 0 <= start <= end <= source["total_chars"]:
            raise ValueError("invalid overview page range")
        ranges[ref].append((start, end))
    complete = {ref for ref, source in sources.items() if _covers(ranges[ref], 0, source["total_chars"])}
    names: set[str] = set()
    classified: set[str] = set()
    output = []
    for topic in topics:
        name = topic.get("name")
        if not isinstance(name, str) or not name.strip() or name.strip() in names:
            raise ValueError("topic names must be nonempty and unique")
        names.add(name.strip())
        evidence = topic.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("each topic requires source locations")
        topic_refs: set[str] = set()
        checked_evidence = []
        for location in evidence:
            ref = location.get("reference_id")
            start, end = location.get("start"), location.get("end")
            if (ref not in refs or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= sources[ref]["total_chars"]
                    or not _covers(ranges[ref], start, end)):
                raise ValueError("topic evidence lies outside inspected source ranges")
            topic_refs.add(ref)
            checked_evidence.append({"reference_id": ref, "start": start, "end": end})
        classified.update(topic_refs)
        output.append({"name": name.strip(), "session_count": len(topic_refs), "evidence": checked_evidence})
    return {
        "success": True,
        "status": "complete" if len(complete) == len(refs) else "partial",
        "classification": "agent_proposed",
        "session_count": len(refs), "fully_read_sessions": len(complete),
        "topic_memberships": sum(item["session_count"] for item in output),
        "topics": sorted(output, key=lambda item: item["name"]),
        "unclassified": sorted(set(refs) - classified),
        "not_fully_read": sorted(set(refs) - complete),
        "processing_unchanged": True,
    }
