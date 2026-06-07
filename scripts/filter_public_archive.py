#!/usr/bin/env python3
"""Remove maintainer-only paths from a public source tarball (see release/public-source-excludes.txt)."""

from __future__ import annotations

import argparse
import io
import tarfile
from pathlib import Path


def _load_excludes(manifest: Path) -> list[str]:
    lines = manifest.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line.rstrip("/"))
    return out


def _rel_member_path(name: str, archive_prefix: str) -> str:
    if archive_prefix and name.startswith(archive_prefix):
        return name[len(archive_prefix) :]
    return name


def _drop_member(rel: str, excludes: list[str]) -> bool:
    for ex in excludes:
        if rel == ex or rel.startswith(ex + "/"):
            return True
    return False


def filter_archive(archive: Path, manifest: Path) -> int:
    excludes = _load_excludes(manifest)
    raw = archive.read_bytes()
    dropped = 0
    buf = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as src:
        prefix = ""
        names = src.getnames()
        if names:
            first = names[0].split("/")[0]
            if first and all(n.startswith(first + "/") or n == first for n in names):
                prefix = first + "/"
        with tarfile.open(fileobj=buf, mode="w:gz") as dst:
            for member in src.getmembers():
                rel = _rel_member_path(member.name, prefix)
                if _drop_member(rel, excludes):
                    dropped += 1
                    continue
                dst.addfile(member, src.extractfile(member))
    archive.write_bytes(buf.getvalue())
    return dropped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "release" / "public-source-excludes.txt",
    )
    args = parser.parse_args()
    n = filter_archive(args.archive, args.manifest)
    print(f"Filtered {n} path(s) from {args.archive}")


if __name__ == "__main__":
    main()
