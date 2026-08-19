"""Run the seven-host native replay against an installed harness-mem wheel."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import tempfile
from pathlib import Path

from harness_mem.adapters import AdapterRegistry
from harness_mem.qualification.host_replay import run_host_replay
from harness_mem.qualification.native_fixtures import (
    QUALIFICATION_HOSTS,
    build_native_fixture_adapter,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _require_installed_wheel() -> None:
    import harness_mem

    checkout_package = Path(__file__).resolve().parents[1] / "harness_mem"
    module_path = Path(harness_mem.__file__).resolve()
    if module_path.is_relative_to(checkout_package):
        raise RuntimeError(
            f"qualification imported checkout source instead of installed wheel: {module_path}"
        )


async def _run(root: Path) -> dict:
    outcomes = []
    for host in QUALIFICATION_HOSTS:
        project = root / "workspace with space" / "项目" / host
        project.mkdir(parents=True)
        project_name = f"qualification-{host}"
        fact = f"{host} native replay preserves the qualified memory path"
        evidence = project / "qualification-evidence.txt"
        evidence.write_text(fact, encoding="utf-8")
        backend = LocalMemoryBackend(root / "data" / host)
        await backend.init()
        try:
            adapter = build_native_fixture_adapter(
                host,
                root=root / "native" / host,
                backend=backend,
                project=project,
                project_name=project_name,
                fact=fact,
            )
            capabilities = AdapterRegistry.capabilities(host)
            if capabilities is None:
                raise RuntimeError(f"missing adapter capabilities: {host}")
            artifact = await run_host_replay(
                host=host,
                adapter=adapter,
                backend=backend,
                project_name=project_name,
                project_root=project,
                candidate_content=fact,
                repository_evidence=evidence,
                artifact_dir=root / "artifacts",
                capabilities=capabilities.to_dict(),
            )
            outcomes.append(artifact.to_dict())
        finally:
            await backend.close()
    return {
        "schema_version": 1,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "hosts": outcomes,
        "success": all(item["status"] == "passed" for item in outcomes),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-installed-wheel", action="store_true")
    args = parser.parse_args()
    if args.require_installed_wheel:
        _require_installed_wheel()
    os.environ.setdefault("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    with tempfile.TemporaryDirectory(prefix="harness-mem-host-replay-") as temp:
        report = asyncio.run(_run(Path(temp)))
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
