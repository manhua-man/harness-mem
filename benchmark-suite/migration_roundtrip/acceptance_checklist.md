# Acceptance Checklist

- Dry-run emits a logical checksum without writing the canonical DB.
- Apply writes only `store_v2/canonical.sqlite`; default v3 JSON storage remains
  the active runtime path.
- Canonical checksum equals dry-run checksum.
- Rollback export checksum equals canonical checksum.
- Any checksum mismatch blocks acceptance.
