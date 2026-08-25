"""
Component tests for jobs.cluster_scan.

Covers:
- scan_cluster_async happy path (footprint probe, then ClusterScanner.scan)
- scan_cluster_async failure path (exception swallowed, task returns normally)
- enqueue_cluster_scan submits the scan to the background pool
"""

from unittest.mock import MagicMock, patch

import pytest

_TASK_MOD = "jobs.cluster_scan"


class TestScanClusterAsync:
    def test_happy_path_calls_scanner(self):
        """scan_cluster_async acquires a DB session and calls ClusterScanner.scan."""
        mock_scanner = MagicMock()
        mock_db = MagicMock()

        with patch(f"{_TASK_MOD}.get_db_context") as mock_ctx, \
             patch(f"{_TASK_MOD}.ClusterScanner") as mock_scanner_cls:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_scanner_cls.return_value = mock_scanner

            from jobs.cluster_scan import scan_cluster_async
            scan_cluster_async(cluster_id=42)

        mock_scanner_cls.assert_called_once_with(mock_db)
        mock_scanner.scan.assert_called_once_with(42)

    def test_scanner_exception_is_swallowed(self):
        """scan_cluster_async logs a warning and returns normally when scanner raises."""
        mock_db = MagicMock()

        with patch(f"{_TASK_MOD}.get_db_context") as mock_ctx, \
             patch(f"{_TASK_MOD}.ClusterScanner") as mock_scanner_cls, \
             patch(f"{_TASK_MOD}.logger") as mock_logger:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_scanner_cls.return_value.scan.side_effect = RuntimeError("kubeconfig broken")

            from jobs.cluster_scan import scan_cluster_async
            # Must not raise
            result = scan_cluster_async(cluster_id=99)

        assert result is None
        mock_logger.warning.assert_called_once()
        assert "99" in str(mock_logger.warning.call_args)

    def test_db_context_exception_is_swallowed(self):
        """scan_cluster_async swallows DB context errors too.

        Two warnings, not one: the footprint probe and the scan each take their
        own session so a scan failure cannot lose the footprint answer, and
        here both fail to get one.
        """
        with patch(f"{_TASK_MOD}.get_db_context") as mock_ctx, \
             patch(f"{_TASK_MOD}.logger") as mock_logger:
            mock_ctx.return_value.__enter__ = MagicMock(side_effect=Exception("db conn failed"))
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            from jobs.cluster_scan import scan_cluster_async
            result = scan_cluster_async(cluster_id=7)

        assert result is None
        assert mock_logger.warning.call_count == 2
        assert all("7" in str(c) for c in mock_logger.warning.call_args_list)


class TestFootprintProbe:
    """The register/update job is what gives a hand-added cluster its
    `meta_data.has_dpf` — the flag that gates the DPF tab. The discovery sweep
    cannot: it matches on context name, and a hand-added cluster's context is
    not in the operator's own kubeconfig."""

    def test_the_footprint_is_probed_before_the_scan(self):
        mock_db = MagicMock()
        mock_cluster = MagicMock()
        mock_db.get.return_value = mock_cluster

        with patch(f"{_TASK_MOD}.get_db_context") as mock_ctx, \
             patch(f"{_TASK_MOD}.ClusterScanner"), \
             patch("services.cluster_discovery_service.refresh_cluster_footprint") as refresh:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            from jobs.cluster_scan import scan_cluster_async
            scan_cluster_async(cluster_id=42)

        refresh.assert_called_once_with(mock_db, mock_cluster)

    def test_a_scan_failure_does_not_lose_the_footprint(self):
        """Separate sessions and separate commits: a cluster with no BNK on it
        fails the scan routinely, and that must not roll back has_dpf."""
        mock_db = MagicMock()

        with patch(f"{_TASK_MOD}.get_db_context") as mock_ctx, \
             patch(f"{_TASK_MOD}.ClusterScanner") as scanner_cls, \
             patch("services.cluster_discovery_service.refresh_cluster_footprint") as refresh:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            scanner_cls.return_value.scan.side_effect = RuntimeError("no BNK here")

            from jobs.cluster_scan import scan_cluster_async
            assert scan_cluster_async(cluster_id=42) is None

        refresh.assert_called_once()
        assert mock_db.commit.called

    def test_a_deleted_cluster_is_skipped(self):
        """The row can be gone by the time the background job runs."""
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch(f"{_TASK_MOD}.get_db_context") as mock_ctx, \
             patch(f"{_TASK_MOD}.ClusterScanner"), \
             patch("services.cluster_discovery_service.refresh_cluster_footprint") as refresh:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            from jobs.cluster_scan import scan_cluster_async
            scan_cluster_async(cluster_id=42)

        refresh.assert_not_called()


class TestEnqueueClusterScan:
    def test_submits_the_scan(self):
        """enqueue_cluster_scan hands the scan to the background pool."""
        with patch("core.background.submit") as mock_submit:
            from jobs.cluster_scan import enqueue_cluster_scan, scan_cluster_async
            enqueue_cluster_scan(42)

        mock_submit.assert_called_once_with(scan_cluster_async, 42)

