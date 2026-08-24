"""Backup and restore against a real SQLite file.

Phase 4 replaced the ``pg_dump``/``psql`` implementation with a tar.gz holding
a SQLite snapshot plus the passphrase-wrapped encryption key. These tests use
real files throughout — the interesting failures (a wrong passphrase, a
truncated archive, a key that does not travel with its database) are all in the
file handling, and mocking it away would test nothing.
"""

import json
import os
import sqlite3
import tarfile
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core import encryption as encryption_module
from core.errors import BackupError, BackupErrorCode
from core.maintenance import clear_maintenance_mode, is_maintenance_mode
from services import backup_service as backup_module
from services.backup_service import (
    DB_MEMBER,
    KEY_MEMBER,
    METADATA_MEMBER,
    BackupService,
)


@pytest.fixture(autouse=True)
def _clear_maintenance():
    clear_maintenance_mode()
    yield
    clear_maintenance_mode()


@pytest.fixture()
def live_db(tmp_path, monkeypatch):
    """A real on-disk SQLite database wired up as the settings DATABASE_URL.

    Returns ``(session, db_path)``. One table with one row is enough: what the
    tests assert is that the row survives the round trip.
    """
    db_path = tmp_path / "bnkscope.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE kubernetes_clusters (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("INSERT INTO kubernetes_clusters (id, name) VALUES (1, 'lab-a')"))

    monkeypatch.setattr(backup_module.settings, "DATABASE_URL", f"sqlite:///{db_path}")
    session = sessionmaker(bind=engine)()
    yield session, db_path
    session.close()
    engine.dispose()


@pytest.fixture()
def key_file(tmp_path, monkeypatch):
    """A Fernet-shaped key on disk, pointed at by both modules that read it."""
    path = tmp_path / "encryption.key"
    path.write_bytes(b"7pKQ0h1vJ8nQ2sV5xY9zB3cD6eF0gH4jK7lM1nO2pQs=")
    monkeypatch.setattr(backup_module, "ENCRYPTION_KEY_FILE", str(path))
    monkeypatch.setattr(encryption_module, "ENCRYPTION_KEY_FILE", str(path))
    return path


class TestCreateBackup:
    def test_archive_holds_the_three_members(self, live_db, key_file):
        session, _ = live_db
        archive = BackupService(session).create_backup("correct horse battery")
        try:
            with tarfile.open(archive) as tar:
                assert set(tar.getnames()) == {DB_MEMBER, KEY_MEMBER, METADATA_MEMBER}
        finally:
            os.unlink(archive)

    def test_snapshot_is_a_readable_database_with_the_rows(self, live_db, key_file, tmp_path):
        """The snapshot must be a real database, not a WAL-torn copy of one."""
        session, _ = live_db
        archive = BackupService(session).create_backup("correct horse battery")
        try:
            with tarfile.open(archive) as tar:
                tar.extract(DB_MEMBER, path=tmp_path / "out", filter="data")
            conn = sqlite3.connect(tmp_path / "out" / DB_MEMBER)
            try:
                rows = conn.execute("SELECT name FROM kubernetes_clusters").fetchall()
            finally:
                conn.close()
            assert rows == [("lab-a",)]
        finally:
            os.unlink(archive)

    def test_metadata_carries_version_and_row_counts(self, live_db, key_file, tmp_path):
        session, _ = live_db
        archive = BackupService(session).create_backup("correct horse battery")
        try:
            with tarfile.open(archive) as tar:
                meta = json.loads(tar.extractfile(METADATA_MEMBER).read().decode())
        finally:
            os.unlink(archive)

        assert meta["engine"] == "sqlite"
        assert meta["version"]
        assert meta["created_at"]
        assert meta["row_counts"]["kubernetes_clusters"] == 1

    def test_absent_tables_are_skipped_not_fatal(self, live_db, key_file):
        """Only one of the metadata tables exists here; the backup still works."""
        session, _ = live_db
        archive = BackupService(session).create_backup("correct horse battery")
        try:
            with tarfile.open(archive) as tar:
                meta = json.loads(tar.extractfile(METADATA_MEMBER).read().decode())
        finally:
            os.unlink(archive)
        assert set(meta["row_counts"]) == {"kubernetes_clusters"}

    def test_wrapped_key_is_not_the_plaintext_key(self, live_db, key_file, tmp_path):
        session, _ = live_db
        archive = BackupService(session).create_backup("correct horse battery")
        try:
            with tarfile.open(archive) as tar:
                blob = tar.extractfile(KEY_MEMBER).read()
        finally:
            os.unlink(archive)

        assert key_file.read_bytes().strip() not in blob
        assert set(json.loads(blob.decode())) == {"salt", "nonce", "ciphertext"}

    def test_refuses_while_a_restore_holds_maintenance_mode(self, live_db, key_file):
        session, _ = live_db
        backup_module.set_maintenance_mode("Restoring from backup")
        with pytest.raises(BackupError) as exc:
            BackupService(session).create_backup("correct horse battery")
        assert exc.value.code == BackupErrorCode.BACKUP_IN_PROGRESS

    def test_refuses_a_non_sqlite_database(self, live_db, key_file, monkeypatch):
        session, _ = live_db
        monkeypatch.setattr(
            backup_module.settings, "DATABASE_URL", "postgresql://forge@localhost/forge"
        )
        with pytest.raises(BackupError) as exc:
            BackupService(session).create_backup("correct horse battery")
        assert exc.value.code == BackupErrorCode.BACKUP_FAILED

    def test_refuses_an_in_memory_database(self, live_db, key_file, monkeypatch):
        session, _ = live_db
        monkeypatch.setattr(backup_module.settings, "DATABASE_URL", "sqlite:///:memory:")
        with pytest.raises(BackupError) as exc:
            BackupService(session).create_backup("correct horse battery")
        assert exc.value.code == BackupErrorCode.BACKUP_FAILED


class TestValidateArchive:
    def test_returns_metadata_for_a_good_archive(self, live_db, key_file):
        session, _ = live_db
        svc = BackupService(session)
        archive = svc.create_backup("correct horse battery")
        try:
            assert svc.validate_archive(archive)["engine"] == "sqlite"
        finally:
            os.unlink(archive)

    def test_rejects_an_archive_missing_the_key(self, live_db, key_file, tmp_path):
        """A database without its key is a database full of unreadable secrets."""
        session, _ = live_db
        incomplete = tmp_path / "incomplete.tar.gz"
        (tmp_path / DB_MEMBER).write_bytes(b"not really a database")
        (tmp_path / METADATA_MEMBER).write_text("{}")
        with tarfile.open(incomplete, "w:gz") as tar:
            tar.add(tmp_path / DB_MEMBER, arcname=DB_MEMBER)
            tar.add(tmp_path / METADATA_MEMBER, arcname=METADATA_MEMBER)

        with pytest.raises(BackupError) as exc:
            BackupService(session).validate_archive(str(incomplete))
        assert exc.value.code == BackupErrorCode.INVALID_ARCHIVE
        assert KEY_MEMBER in str(exc.value)

    def test_rejects_a_file_that_is_not_a_tarball(self, live_db, key_file, tmp_path):
        session, _ = live_db
        junk = tmp_path / "junk.tar.gz"
        junk.write_bytes(b"\x00\x01\x02 definitely not gzip")
        with pytest.raises(BackupError) as exc:
            BackupService(session).validate_archive(str(junk))
        assert exc.value.code == BackupErrorCode.INVALID_ARCHIVE


class TestRestoreBackup:
    def test_round_trip_restores_rows_and_key(self, live_db, key_file):
        session, db_path = live_db
        svc = BackupService(session)
        original_key = key_file.read_bytes()
        archive = svc.create_backup("correct horse battery")

        try:
            # Diverge both the database and the key from what was backed up.
            session.execute(text("DELETE FROM kubernetes_clusters"))
            session.commit()
            key_file.write_bytes(b"XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX=")

            result = svc.restore_backup(archive, "correct horse battery")
        finally:
            os.unlink(archive)

        assert result["restart_required"] is True
        assert result["restored_from"]["row_counts"]["kubernetes_clusters"] == 1
        assert key_file.read_bytes() == original_key

        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute("SELECT name FROM kubernetes_clusters").fetchall() == [("lab-a",)]
        finally:
            conn.close()

    def test_wrong_passphrase_leaves_the_database_untouched(self, live_db, key_file):
        """Unwrap must fail *before* anything is overwritten."""
        session, db_path = live_db
        svc = BackupService(session)
        archive = svc.create_backup("correct horse battery")

        try:
            session.execute(text("INSERT INTO kubernetes_clusters (id, name) VALUES (2, 'lab-b')"))
            session.commit()

            with pytest.raises(BackupError) as exc:
                svc.restore_backup(archive, "wrong passphrase entirely")
        finally:
            os.unlink(archive)

        assert exc.value.code == BackupErrorCode.INVALID_PASSPHRASE
        conn = sqlite3.connect(db_path)
        try:
            names = {r[0] for r in conn.execute("SELECT name FROM kubernetes_clusters")}
        finally:
            conn.close()
        assert names == {"lab-a", "lab-b"}

    def test_maintenance_mode_is_released_even_when_the_restore_fails(self, live_db, key_file):
        """A wedged flag would leave the API refusing every request."""
        session, _ = live_db
        svc = BackupService(session)
        archive = svc.create_backup("correct horse battery")
        try:
            with pytest.raises(BackupError):
                svc.restore_backup(archive, "wrong passphrase entirely")
        finally:
            os.unlink(archive)
        assert is_maintenance_mode() is False

    def test_stale_wal_files_are_removed(self, live_db, key_file):
        """A leftover -wal would be replayed on top of the restored file."""
        session, db_path = live_db
        svc = BackupService(session)
        archive = svc.create_backup("correct horse battery")
        stale = Path(str(db_path) + "-wal")
        stale.write_bytes(b"stale wal")
        try:
            svc.restore_backup(archive, "correct horse battery")
        finally:
            os.unlink(archive)
        assert not stale.exists()

    def test_refuses_while_another_operation_holds_maintenance_mode(self, live_db, key_file):
        session, _ = live_db
        svc = BackupService(session)
        archive = svc.create_backup("correct horse battery")
        try:
            backup_module.set_maintenance_mode("Restoring from backup")
            with pytest.raises(BackupError) as exc:
                svc.restore_backup(archive, "correct horse battery")
        finally:
            os.unlink(archive)
        assert exc.value.code == BackupErrorCode.BACKUP_IN_PROGRESS


class TestBackupStatus:
    def test_idle_when_nothing_is_running(self, live_db, key_file):
        session, _ = live_db
        status = BackupService(session).get_backup_status()
        assert status == {
            "in_progress": False,
            "operation": None,
            "started_at": None,
            "message": None,
        }

    def test_reports_a_restore_in_flight(self, live_db, key_file):
        session, _ = live_db
        backup_module.set_maintenance_mode("Restoring from backup")
        status = BackupService(session).get_backup_status()
        assert status["in_progress"] is True
        assert status["operation"] == "restore"
        assert status["message"] == "Restoring from backup"
        assert status["started_at"]


def test_archive_is_written_outside_the_repository(live_db, key_file):
    """The archive is a temp file the caller streams and then unlinks."""
    session, _ = live_db
    archive = BackupService(session).create_backup("correct horse battery")
    try:
        assert archive.startswith(tempfile.gettempdir())
        assert "bnkscope-backup-" in os.path.basename(archive)
    finally:
        os.unlink(archive)
