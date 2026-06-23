"""Local Memory Index Fabric contracts."""

from harness_mem.index_fabric.manifest import (
    CURRENT_MANIFEST_NAME,
    INDEX_FABRIC_SCHEMA_VERSION,
    BuildMetrics,
    IndexManifest,
    IndexSidecar,
    build_index_generation,
    ensure_index_current,
    load_current_manifest,
    source_fingerprint,
)

__all__ = [
    "INDEX_FABRIC_SCHEMA_VERSION",
    "CURRENT_MANIFEST_NAME",
    "BuildMetrics",
    "IndexManifest",
    "IndexSidecar",
    "build_index_generation",
    "ensure_index_current",
    "load_current_manifest",
    "source_fingerprint",
]
