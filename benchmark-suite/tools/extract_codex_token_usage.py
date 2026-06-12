from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return value
    return None


def _has_usage(value: dict[str, Any]) -> bool:
    return any(
        _number(value.get(key)) is not None
        for key in [
            "total_tokens",
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "reasoning_tokens",
        ]
    )


def _usage_total(value: dict[str, Any]) -> int | float | None:
    total = _number(value.get("total_tokens"))
    if total is not None:
        return total
    parts = [
        _number(value.get("input_tokens")),
        _number(value.get("cached_input_tokens")),
        _number(value.get("output_tokens")),
        _number(value.get("reasoning_output_tokens"))
        or _number(value.get("reasoning_tokens")),
    ]
    numeric = [part for part in parts if part is not None]
    return sum(numeric) if numeric else None


def _token_count_info(event: dict[str, Any]) -> dict[str, Any] | None:
    payload = event.get("payload")
    if isinstance(payload, dict) and payload.get("type") == "token_count":
        info = payload.get("info")
        return info if isinstance(info, dict) else None
    if event.get("type") == "token_count":
        info = event.get("info")
        return info if isinstance(info, dict) else None
    return None


def _iter_token_count_events(path: Path):
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        info = _token_count_info(event)
        if info is not None:
            yield line_number, event, info


def _candidate_usages(path: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for line_number, event, info in _iter_token_count_events(path):
        for field_name, usage_kind in [
            ("last_token_usage", "last"),
            ("total_token_usage", "total"),
        ]:
            usage = info.get(field_name)
            if isinstance(usage, dict) and _has_usage(usage):
                candidates.append(
                    {
                        "line_number": line_number,
                        "timestamp": event.get("timestamp"),
                        "usage_kind": usage_kind,
                        "usage": usage,
                    }
                )
    return candidates


def select_usage(path: Path, usage_kind: str = "auto") -> dict[str, Any]:
    candidates = _candidate_usages(path)
    if not candidates:
        raise SystemExit(f"{path}: no token_count usage events found")

    if usage_kind == "auto":
        non_zero_last = [
            candidate
            for candidate in candidates
            if candidate["usage_kind"] == "last"
            and (_usage_total(candidate["usage"]) or 0) > 0
        ]
        if non_zero_last:
            return non_zero_last[-1]
        non_zero_total = [
            candidate for candidate in candidates if (_usage_total(candidate["usage"]) or 0) > 0
        ]
        return non_zero_total[-1] if non_zero_total else candidates[-1]

    matching = [candidate for candidate in candidates if candidate["usage_kind"] == usage_kind]
    if not matching:
        raise SystemExit(f"{path}: no {usage_kind}_token_usage event found")
    return matching[-1]


def build_sidecar(path: Path, usage_kind: str = "auto") -> dict[str, Any]:
    selected = select_usage(path, usage_kind)
    usage = selected["usage"]
    reasoning = _number(usage.get("reasoning_output_tokens")) or _number(
        usage.get("reasoning_tokens")
    )
    total = _usage_total(usage)
    return {
        "available": True,
        "source": "codex-session-observer",
        "total": total,
        "input": _number(usage.get("input_tokens")),
        "cached_input": _number(usage.get("cached_input_tokens")),
        "output": _number(usage.get("output_tokens")),
        "reasoning": reasoning,
        "cost_usd": None,
        "notes": [
            (
                "Extracted only numeric token_count fields from Codex JSONL; "
                "prompt, message, and tool-output text were not copied."
            ),
            (
                f"Selected {selected['usage_kind']}_token_usage at line "
                f"{selected['line_number']}."
            ),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract a BENCH-001 token_usage sidecar from Codex JSONL."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--usage",
        choices=["auto", "last", "total"],
        default="auto",
        help="Which token_count payload to export. auto prefers a non-zero last_token_usage.",
    )
    args = parser.parse_args()

    sidecar = build_sidecar(args.input, args.usage)
    text = json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
