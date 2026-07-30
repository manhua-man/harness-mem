# Legacy Storage Reader Lifecycle

Legacy JSON storage readers are deprecated in 0.9.6 but remain supported for
the complete 0.9.x line. They cannot be removed before both of these gates:

```text
earliest version: 1.0.0
earliest date:    2027-01-31
```

The later gate wins. Removal also requires an explicit converter to have
shipped in a stable release, Doctor to report canonical data verified without
conflict, and release notes to name the actual removal version.

This lifecycle covers only the legacy entity JSON roots under `data/verbatim`
and `data/structured`, plus their degraded runtime fallback. It does not cover
transcript-ledger schema migration, `status=accepted` governance migration,
Codex archive import, or legacy configuration JSON.

## Authority transition

Existing legacy data never changes storage authority during ordinary startup.
When legacy rows exist and canonical SQLite is absent, runtime remains on the
lossless legacy fallback and Doctor reports `migration_required`.

Migration is always:

```text
preview all projects
-> explicit --apply
-> receipt-first staging and snapshot
-> integrity/checksum/conflict validation
-> transaction-locked live fingerprint check
-> in-place atomic activation for existing SQLite / create-if-absent for new SQLite
-> succeeded/failed receipt
```

Preview:

```bash
harness-mem maintenance migrate-store-v2 \
  --project <PROJECT_NAME> --dry-run
```

Apply after reviewing the global plan:

```bash
harness-mem maintenance migrate-store-v2 \
  --project <PROJECT_NAME> --apply
```

The project argument identifies the operator context; activation scope is
always `all_projects` because one data directory has one canonical authority.
Receipts live under `store_v2/migration_receipts/`, contain checksums/counts and
stable failure metadata, and never copy entity or transcript content. Receipt
persistence failure blocks or rolls back activation.

For an existing canonical database, activation updates the same SQLite file in
one `BEGIN IMMEDIATE` transaction. Already-open runtimes therefore stay on the
live database instead of an unlinked pre-migration file. A writer that commits
after staging began makes the fingerprint check fail closed. When no canonical
database exists, activation uses an atomic create-if-absent link and refuses to
overwrite a database created concurrently.

Invalid legacy JSON and legacy/canonical content conflicts are manual-review
states. Doctor may show a preview command, but it does not expose an apply
command until the conflict is resolved.

The compatibility `--export-rollback` option uses the current canonical entity
exporter, so canonical-only rows created after migration are included. Legacy
files are not automatically deleted by migration.
