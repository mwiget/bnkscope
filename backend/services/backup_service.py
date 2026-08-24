"""Backup and restore.

A bnkscope backup is a tar.gz holding three things:

  ``bnkscope.db``    a consistent copy of the SQLite database
  ``encryption.key.wrapped`` the Fernet key, wrapped with the user's passphrase
  ``metadata.json``  version, row counts, timestamp

The key has to travel with the database: kubeconfigs and cloud credentials are
stored encrypted, so a database restored without its key is a database full of
unreadable secrets.

This was ``pg_dump``/``psql`` until Phase 4. The consistent copy now comes from
SQLite's own backup API rather than a text dump — it takes a proper snapshot
while other connections keep reading, which a filesystem copy of a WAL-mode
database does not.
"""

import json
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from core.config import settings
from core.encryption import ENCRYPTION_KEY_FILE, unwrap_fernet_key, wrap_fernet_key
from core.errors import BackupError, BackupErrorCode
from core.maintenance import (
    clear_maintenance_mode,
    get_maintenance_status,
    is_maintenance_mode,
    set_maintenance_mode,
)

logger = logging.getLogger(__name__)

DB_MEMBER = "bnkscope.db"
KEY_MEMBER = "encryption.key.wrapped"
METADATA_MEMBER = "metadata.json"

# Counted into metadata so a restore can be sanity-checked against the source.
# Missing tables are skipped rather than failing the backup.
METADATA_TABLES = [
    "kubernetes_clusters",
    "cloud_credential_templates",
    "alert_channels",
    "notifications",
    "application_settings",
]


def _database_path() -> str:
    """Absolute path of the SQLite file behind DATABASE_URL."""
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        raise BackupError(
            BackupErrorCode.BACKUP_FAILED,
            f"Backup supports SQLite only; DATABASE_URL is {url.split(':', 1)[0]}",
        )
    path = url.split("sqlite:///", 1)[-1]
    if not path or path == ":memory:":
        raise BackupError(BackupErrorCode.BACKUP_FAILED, "Cannot back up an in-memory database")
    return path


class BackupService:
    """Create and restore bnkscope backups."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_backup(self, passphrase: str) -> str:
        """Create a backup archive and return its path (caller cleans up)."""
        if is_maintenance_mode():
            raise BackupError(
                BackupErrorCode.BACKUP_IN_PROGRESS,
                "Another backup/restore operation is in progress",
            )

        logger.info("Starting backup creation")
        tmp_dir = tempfile.mkdtemp(prefix="bnkscope-backup-")
        try:
            self._snapshot_database(os.path.join(tmp_dir, DB_MEMBER))
            self._wrap_encryption_key(passphrase, os.path.join(tmp_dir, KEY_MEMBER))
            self._write_metadata(os.path.join(tmp_dir, METADATA_MEMBER))

            fd, archive_path = tempfile.mkstemp(
                prefix=f"bnkscope-backup-{datetime.now(UTC):%Y%m%d-%H%M%S}-", suffix=".tar.gz"
            )
            os.close(fd)
            with tarfile.open(archive_path, "w:gz") as tar:
                for member in (DB_MEMBER, KEY_MEMBER, METADATA_MEMBER):
                    tar.add(os.path.join(tmp_dir, member), arcname=member)

            logger.info("Backup created: %s", archive_path)
            return archive_path
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _snapshot_database(self, output_path: str) -> None:
        """Copy the database with SQLite's backup API.

        This is not `cp`: it takes a transactionally consistent snapshot while
        other connections are still reading and writing, which matters because
        the reachability probe and the scheduler are always live.
        """
        src_path = _database_path()
        try:
            src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
            try:
                dst = sqlite3.connect(output_path)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
        except sqlite3.Error as exc:
            raise BackupError(
                BackupErrorCode.BACKUP_FAILED, f"Database snapshot failed: {exc}"
            ) from exc

    def _wrap_encryption_key(self, passphrase: str, output_path: str) -> None:
        """Wrap the Fernet key with the passphrase and write it to the archive.

        ``wrap_fernet_key`` returns a ``{salt, nonce, ciphertext}`` dict of
        base64 strings; the archive member is that dict as JSON.
        """
        try:
            key = Path(ENCRYPTION_KEY_FILE).read_bytes().strip()
        except OSError as exc:
            raise BackupError(
                BackupErrorCode.BACKUP_FAILED, f"Cannot read encryption key: {exc}"
            ) from exc
        Path(output_path).write_text(json.dumps(wrap_fernet_key(key, passphrase)))

    def _write_metadata(self, output_path: str) -> None:
        counts: dict[str, int] = {}
        existing = set(inspect(self.db.get_bind()).get_table_names())
        for table in METADATA_TABLES:
            if table not in existing:
                continue
            try:
                counts[table] = int(
                    self.db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0  # noqa: S608
                )
            except Exception:  # noqa: BLE001 — metadata is advisory
                logger.debug("Could not count rows in %s", table)
        Path(output_path).write_text(
            json.dumps(
                {
                    "version": settings.VERSION,
                    "created_at": datetime.now(UTC).isoformat(),
                    "engine": "sqlite",
                    "row_counts": counts,
                },
                indent=2,
            )
        )

    # ------------------------------------------------------------------
    # Inspect / restore
    # ------------------------------------------------------------------

    def validate_archive(self, archive_path: str) -> dict:
        """Check the archive has the three expected members; return its metadata."""
        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                names = set(tar.getnames())
                missing = {DB_MEMBER, KEY_MEMBER, METADATA_MEMBER} - names
                if missing:
                    raise BackupError(
                        BackupErrorCode.INVALID_ARCHIVE,
                        f"Archive is missing: {', '.join(sorted(missing))}",
                    )
                meta_file = tar.extractfile(METADATA_MEMBER)
                metadata = json.loads(meta_file.read().decode()) if meta_file else {}
        except tarfile.TarError as exc:
            raise BackupError(
                BackupErrorCode.INVALID_ARCHIVE, f"Cannot read archive: {exc}"
            ) from exc
        return dict(metadata)

    def restore_backup(self, archive_path: str, passphrase: str) -> dict:
        """Replace the live database and encryption key from an archive.

        Destructive and not reversible: the current database is overwritten.
        Maintenance mode is held for the duration so requests are refused
        rather than served from a half-restored database.
        """
        metadata = self.validate_archive(archive_path)
        if is_maintenance_mode():
            raise BackupError(
                BackupErrorCode.BACKUP_IN_PROGRESS,
                "Another backup/restore operation is in progress",
            )

        set_maintenance_mode("Restoring from backup")
        tmp_dir = tempfile.mkdtemp(prefix="bnkscope-restore-")
        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                for member in (DB_MEMBER, KEY_MEMBER):
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        raise BackupError(
                            BackupErrorCode.INVALID_ARCHIVE, f"Archive member {member} is unreadable"
                        )
                    Path(os.path.join(tmp_dir, member)).write_bytes(extracted.read())

            # Unwrap first: a wrong passphrase must fail before anything is
            # overwritten, or the operator is left with a database they cannot
            # decrypt and no way back.
            try:
                wrapped = json.loads(Path(os.path.join(tmp_dir, KEY_MEMBER)).read_text())
                key = unwrap_fernet_key(wrapped, passphrase)
            except Exception as exc:  # noqa: BLE001
                raise BackupError(
                    BackupErrorCode.INVALID_PASSPHRASE,
                    "Could not unwrap the encryption key — wrong passphrase?",
                ) from exc

            db_path = _database_path()
            # Drop pooled connections so the file is not held open mid-swap.
            self.db.get_bind().dispose()
            shutil.copyfile(os.path.join(tmp_dir, DB_MEMBER), db_path)
            for suffix in ("-wal", "-shm"):
                stale = Path(db_path + suffix)
                if stale.exists():
                    stale.unlink()
            Path(ENCRYPTION_KEY_FILE).write_bytes(key)

            logger.warning("Restore complete — restart bnkscope to pick up the restored database")
            return {
                "restored_from": metadata,
                "restart_required": True,
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            clear_maintenance_mode()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_backup_status(self) -> dict[str, object]:
        """Report whether a backup/restore is running."""
        status = get_maintenance_status()
        if status:
            return {
                "in_progress": True,
                "operation": "restore",  # maintenance mode is only set during restore
                "started_at": status.get("started_at"),
                "message": status.get("message"),
            }
        return {
            "in_progress": False,
            "operation": None,
            "started_at": None,
            "message": None,
        }
