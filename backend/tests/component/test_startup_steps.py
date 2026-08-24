"""Tests for startup initialization steps."""

from unittest.mock import MagicMock, call, patch

from startup_steps import seed_defaults_step


def _make_db_context(db):
    """Return a context manager mock that yields *db*."""
    ctx = MagicMock()
    ctx.__enter__.return_value = db
    ctx.__exit__.return_value = False
    return ctx


def _mock_db_for_git_url(url: str | None):
    """Build a db mock that returns a git_url ApplicationSetting and no ModuleSource."""
    db = MagicMock()

    def _query_side_effect(model):
        q = MagicMock()

        class _Filter:
            def __init__(self):
                self._call_count = 0

            def filter(self, *args, **kwargs):
                self._call_count += 1
                inner = MagicMock()
                # first filter call → ApplicationSetting (git_url)
                if self._call_count == 1:
                    setting = MagicMock()
                    setting.value = url
                    inner.first.return_value = setting if url is not None else None
                else:
                    # ModuleSource lookup — no row by default
                    inner.first.return_value = None
                return inner

        f = _Filter()
        q.filter = f.filter
        return q

    db.query.side_effect = _query_side_effect
    # SQLite dialect (tests bypass Postgres advisory lock)
    db.bind.dialect.name = "sqlite"
    return db


