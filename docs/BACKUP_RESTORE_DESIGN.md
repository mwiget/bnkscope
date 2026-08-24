# Backup & Restore

> What a bnkscope backup contains, and what restoring one does.

Reachable from **System → Backup & Restore**. Implemented in
`backend/services/backup_service.py`.

---

## What is in a backup

A `tar.gz` holding exactly three members:

| Member | What it is |
|---|---|
| `bnkscope.db` | A consistent copy of the SQLite database |
| `encryption.key.wrapped` | The Fernet key, wrapped with your passphrase |
| `metadata.json` | Version, engine, timestamp, per-table row counts |

**The key travels with the database, and that is the point.** Kubeconfigs and
cloud credentials are stored encrypted, so a database restored without its key is
a database full of unreadable secrets. It is wrapped with a passphrase you
choose, so the archive is not itself a credential — losing the passphrase means
losing the backup.

The database copy comes from **SQLite's own backup API**, not a file copy: it
takes a proper snapshot while other connections keep reading, which copying a
WAL-mode database file cannot do safely.

## What is *not* in a backup

Nothing from your machine. `~/.kube`, `~/.aws`, `~/.config/gcloud` and
`~/.config/tmmscope` are mounted read-only and are never written or captured —
after a restore, cluster discovery simply reads your kubeconfig again.

## Restore

`validate_archive()` checks the three members are present and returns the
metadata, so the UI can show you what you are about to restore before it does
anything. `restore_backup()` then **replaces** the live database and encryption
key — it is a full replace, not a merge.

Use it to move an instance to another machine, or to roll back after something
went wrong.

## Why it no longer mentions Postgres or Alembic

This was `pg_dump` / `psql` with an Alembic forward-migration step until Phase 4,
when Postgres and Alembic both went. The schema is now created by
`Base.metadata.create_all`, so there is no migration to run on restore, and the
old design's cross-version story went with it: **restore into the same major
version you backed up from.** `metadata.json` records the version so a mismatch
is visible rather than silent.

---

| | |
|---|---|
| [User Guide](USER_GUIDE.md#system) | where to find it in the UI |
| [Troubleshooting](TROUBLESHOOTING.md#starting-over) | `bnkscope down --purge` |
