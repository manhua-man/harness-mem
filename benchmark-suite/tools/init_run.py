from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "suite.json"
TEMPLATES = ROOT / "templates"
ARTIFACTS = ROOT / "artifacts"


def load_suite() -> dict:
    return json.loads(SUITE_PATH.read_text(encoding="utf-8"))


def render_manifest(args: argparse.Namespace) -> dict:
    template = json.loads(
        (TEMPLATES / "run_manifest.template.json").read_text(encoding="utf-8")
    )
    template["benchmark_id"] = args.benchmark_id
    template["run_name"] = args.run_name
    template["created_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    template["client"] = args.client
    template["model"] = args.model
    template["workspace_path"] = args.workspace
    template["repo_state"]["git_head"] = args.git_head or "unknown"
    template["repo_state"]["git_dirty"] = args.git_dirty
    return template


def build_run_dir(args: argparse.Namespace) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d")
    name = f"{stamp}-{args.benchmark_id}-{args.run_name}"
    return ARTIFACTS / name


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a benchmark run skeleton.")
    parser.add_argument("--benchmark-id", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--git-head")
    parser.add_argument("--git-dirty", action="store_true")
    args = parser.parse_args()

    suite = load_suite()
    ids = {item["id"] for item in suite["collections"]}
    if args.benchmark_id not in ids:
        raise SystemExit(f"Unknown benchmark id: {args.benchmark_id}")

    run_dir = build_run_dir(args)
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "results").mkdir()
    (run_dir / "transcripts").mkdir()
    (run_dir / "notes").mkdir()

    manifest = render_manifest(args)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(
        (TEMPLATES / "report.template.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (run_dir / "results" / "task-result.sample.json").write_text(
        (TEMPLATES / "task_result.template.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
