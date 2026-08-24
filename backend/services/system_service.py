"""
System Service — DB and business logic for system administration.

Extracted from routes/system.py to separate HTTP handling from domain logic.

Covers:
- System health checks (SQLite)
- Performance metrics
- Recent errors
- Database stats, cleanup, vacuum
- System version check and upgrade
"""

import logging
import os
import subprocess
import threading
import time
from datetime import UTC, datetime
from typing import Any

import requests
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from core.cache import cache
from models import ApplicationSetting
from services.defaults_service import DEFAULT_REPO_URL

logger = logging.getLogger(__name__)


class SystemService:
    """Service layer for system monitoring and administration."""

    def __init__(self, db: Session):
        self.db = db

    # ================================================================
    # Health
    # ================================================================

    def get_health(self) -> dict[str, Any]:
        """Get comprehensive system health status (cached 30s)."""
        cached = cache.get("system:health")
        if cached:
            return cached

        health_data = {"services": {}, "timestamp": datetime.now(UTC).isoformat()}

        # Backend
        backend_start = time.time()
        health_data["services"]["backend"] = {
            "status": "healthy",
            "response_time_ms": round((time.time() - backend_start) * 1000, 2)
        }

        # Database
        try:
            db_start = time.time()
            self.db.execute(text("SELECT 1"))
            health_data["services"]["database"] = {
                "status": "healthy",
                "response_time_ms": round((time.time() - db_start) * 1000, 2)
            }
        except Exception as e:
            health_data["services"]["database"] = {"status": "offline", "error": str(e)}

        # Redis and the Celery worker pool used to be probed here too. They are
        # in-process now (Phase 4), so the two services above are the whole list.
        cache.set("system:health", health_data, 30)
        return health_data

    # ================================================================
    # Database Management
    # ================================================================

    def _database_size_mb(self) -> float:
        """On-disk size of the SQLite database, including its WAL."""
        from database import DATABASE_URL, IS_SQLITE

        if not IS_SQLITE:
            return 0.0
        path = DATABASE_URL.split("sqlite:///", 1)[-1]
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += os.path.getsize(path + suffix)
            except OSError:
                pass
        return round(total / (1024 * 1024), 2)

    def get_database_stats(self) -> dict[str, Any]:
        """Database size plus a per-table row count."""
        from sqlalchemy import inspect as sa_inspect

        table_stats: dict[str, Any] = {}
        for table in sorted(sa_inspect(self.db.get_bind()).get_table_names()):
            try:
                rows = int(self.db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)  # noqa: S608
            except Exception:  # noqa: BLE001 — a stats panel must not 500
                continue
            table_stats[table] = {"rows": rows}

        return {"size_mb": self._database_size_mb(), "tables": table_stats}

    def vacuum_database(self) -> dict[str, Any]:
        """Run VACUUM to reclaim space from deleted rows.

        SQLite's VACUUM cannot run inside a transaction, so the session is
        committed first and the statement issued on the raw DBAPI connection
        with autocommit semantics.
        """
        start_time = time.time()
        self.db.commit()
        try:
            connection = self.db.connection().connection
            connection.isolation_level = None  # autocommit — VACUUM needs it
            cursor = connection.cursor()
            try:
                cursor.execute("VACUUM")
            finally:
                cursor.close()
                connection.isolation_level = ""
        except Exception as e:  # noqa: BLE001
            logger.warning("VACUUM failed: %s", e)
            return {
                "status": "skipped",
                "message": f"VACUUM did not run: {e}",
                "duration_seconds": 0,
            }

        duration = round(time.time() - start_time, 2)
        logger.info("Database vacuum completed in %ss", duration)
        return {"status": "success", "duration_seconds": duration}

    # ================================================================
    # Performance / errors
    # ================================================================

    def get_performance_metrics(self) -> dict[str, Any]:
        """System performance metrics (cached 30s)."""
        cache_key = "system:performance"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        metrics: dict[str, Any] = {
            "api": {},
            "database": {"size_mb": self._database_size_mb()},
            "tasks": {},
        }
        cache.set(cache_key, metrics, ttl_seconds=30)
        return metrics

    def get_recent_errors(self, limit: int = 10) -> dict[str, Any]:
        """Recent failures.

        The task/operations log this read was the pipeline's and went with it
        (Phase 1). The endpoint stays so the System panel keeps its shape.
        """
        return {"errors": [], "total": 0}

    # ================================================================
    # Version & Upgrade
    # ================================================================

    def get_system_version(self) -> dict[str, Any]:
        """Get current and available system versions."""
        result = {
            "current_version": "unknown", "latest_version": "unknown",
            "update_available": False, "commits_behind": 0, "error": None
        }

        version_paths = ["/app/VERSION", "/VERSION", "VERSION", "/app/data/VERSION"]
        for version_file in version_paths:
            if os.path.exists(version_file):
                with open(version_file) as f:
                    result["current_version"] = f.read().strip()
                break

        # Get GitHub PAT (optional — used for private repos)
        git_token = ""
        try:
            from core.encryption import decrypt_value_or_none
            pat_setting = self.db.query(ApplicationSetting).filter(
                ApplicationSetting.key == "module_library.git_token"
            ).first()
            if pat_setting and pat_setting.value:
                git_token = pat_setting.value
                if pat_setting.is_encrypted:
                    git_token = decrypt_value_or_none(git_token) or git_token
                if git_token.lower() in ["change_me", "", "your_token_here", "placeholder"]:
                    git_token = ""
        except Exception as e:
            logger.warning(f"Could not load GitHub PAT from settings: {e}")

        # Get update repo URL from DB (configurable via System > Defaults)
        repo_url = DEFAULT_REPO_URL
        try:
            repo_setting = self.db.query(ApplicationSetting).filter(
                ApplicationSetting.key == "system.update_repo_url"
            ).first()
            if repo_setting and repo_setting.value:
                repo_url = repo_setting.value.rstrip("/")
        except Exception as e:
            logger.warning(f"Could not load update repo URL from settings: {e}")

        # Derive raw content URL from repo URL
        # Supports: https://github.com/owner/repo or https://github.com/owner/repo.git
        raw_url = ""
        try:
            clean_url = repo_url.rstrip("/").removesuffix(".git")
            if "github.com" in clean_url:
                # GitHub: https://raw.githubusercontent.com/owner/repo/main/VERSION
                raw_url = clean_url.replace("github.com", "raw.githubusercontent.com") + "/main/VERSION"
            elif "gitswarm" in clean_url or "gitlab" in clean_url:
                # GitLab/GitSwarm: https://host/group/project/-/raw/main/VERSION
                raw_url = clean_url + "/-/raw/main/VERSION"
            else:
                # Fallback: assume GitHub-like raw URL
                raw_url = clean_url.replace("github.com", "raw.githubusercontent.com") + "/main/VERSION"
        except Exception as e:
            logger.warning(f"Could not derive raw URL from {repo_url}: {e}")

        if not raw_url:
            # Silently skip version check if we can't build a URL
            return result

        try:
            headers = {"Authorization": f"token {git_token}"} if git_token else {}
            response = requests.get(raw_url, headers=headers, timeout=10)

            if response.status_code == 200:
                result["latest_version"] = response.text.strip()
                current = result["current_version"]
                latest = result["latest_version"]

                if current != "unknown" and latest != "unknown":
                    try:
                        current_parts = [int(x) for x in current.split('.')]
                        latest_parts = [int(x) for x in latest.split('.')]
                        while len(current_parts) < len(latest_parts):
                            current_parts.append(0)
                        while len(latest_parts) < len(current_parts):
                            latest_parts.append(0)
                        result["update_available"] = latest_parts > current_parts
                        if result["update_available"]:
                            major_diff = latest_parts[0] - current_parts[0]
                            minor_diff = latest_parts[1] - current_parts[1] if len(latest_parts) > 1 else 0
                            patch_diff = latest_parts[2] - current_parts[2] if len(latest_parts) > 2 else 0
                            result["commits_behind"] = max(1, major_diff * 100 + minor_diff * 10 + patch_diff)
                    except (ValueError, IndexError):
                        result["update_available"] = current != latest
                        if result["update_available"]:
                            result["commits_behind"] = 1
            elif response.status_code == 404:
                # Silently handle — repo may be private or not yet created
                logger.info(f"Version check returned 404 for {raw_url} — repo may be private or inaccessible")
            elif response.status_code == 403:
                # Rate limit or auth issue — only warn, don't show error to user
                logger.info(f"Version check returned 403 for {raw_url} — rate limited or auth required")
            else:
                logger.info(f"Version check returned {response.status_code} for {raw_url}")
        except requests.exceptions.Timeout:
            logger.info("Version check timed out — network may be unavailable")
        except requests.exceptions.ConnectionError:
            # Graceful handling for local/offline mode
            logger.info("Version check failed — no network connectivity (local mode?)")
        except requests.exceptions.RequestException as e:
            logger.info(f"Version check failed: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error during version check: {e}")

        return result

    # ================================================================
    # Upgrade Lock — prevent deployments while system is upgrading
    # ================================================================

    _upgrade_in_progress = False

    @classmethod
    def is_upgrade_in_progress(cls) -> bool:
        """Check if a system upgrade is currently running."""
        return cls._upgrade_in_progress

    # ---- Upgrade state persistence (UP-003) ----

    _UPGRADE_STATE_KEY = "system.upgrade_state"

    @staticmethod
    def _save_upgrade_state_standalone(state: dict[str, Any]) -> None:
        """Persist upgrade state from the background thread (creates its own DB session).

        The upgrade runs in a daemon thread that outlives the request-scoped session,
        so we open a short-lived session, write, commit, close.  Best-effort — never
        lets a DB error interrupt the upgrade.
        """
        import json as _json
        try:
            from database import SessionLocal
            db = SessionLocal()
            try:
                setting = db.query(ApplicationSetting).filter(
                    ApplicationSetting.key == SystemService._UPGRADE_STATE_KEY
                ).first()
                value = _json.dumps(state)
                if setting:
                    setting.value = value
                    setting.updated_at = datetime.now(UTC)
                else:
                    db.add(ApplicationSetting(
                        key=SystemService._UPGRADE_STATE_KEY,
                        value=value,
                        value_type="json",
                        category="system",
                        description="Last system upgrade state (persisted across restarts)",
                    ))
                db.commit()
            except Exception as e:
                logger.warning(f"Failed to save upgrade state: {e}")
                try:
                    db.rollback()
                except Exception:
                    pass
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to create DB session for upgrade state: {e}")

    def _save_upgrade_state(self, state: dict[str, Any]) -> None:
        """Persist upgrade state using the request-scoped session (for pre-thread calls)."""
        import json as _json
        try:
            setting = self.db.query(ApplicationSetting).filter(
                ApplicationSetting.key == self._UPGRADE_STATE_KEY
            ).first()
            value = _json.dumps(state)
            if setting:
                setting.value = value
                setting.updated_at = datetime.now(UTC)
            else:
                self.db.add(ApplicationSetting(
                    key=self._UPGRADE_STATE_KEY,
                    value=value,
                    value_type="json",
                    category="system",
                    description="Last system upgrade state (persisted across restarts)",
                ))
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to save upgrade state: {e}")
            try:
                self.db.rollback()
            except Exception:
                pass

    def get_upgrade_state(self) -> dict[str, Any] | None:
        """Read the persisted upgrade state from DB.

        Returns a dict with keys: status, old_version, new_version,
        started_at, completed_at, current_phase, phase_label, log (list of lines).
        """
        import json as _json
        try:
            setting = self.db.query(ApplicationSetting).filter(
                ApplicationSetting.key == self._UPGRADE_STATE_KEY
            ).first()
            if setting and setting.value:
                return _json.loads(setting.value)
        except Exception as e:
            logger.warning(f"Failed to read upgrade state: {e}")
        return None

    def get_upgrade_readiness(self) -> dict[str, Any]:
        """Pre-flight check: can the GUI trigger an upgrade?"""
        host_repo_path = os.environ.get("HOST_REPO_PATH", "")
        docker_sock = os.path.exists("/var/run/docker.sock")
        deployment_mode = "local" if os.environ.get("BNK_FORGE_DEPLOY_MODE") == "local" else "server"
        if deployment_mode == "local":
            recommended_command = "make local-deploy"
            recommended_label = "Local redeploy"
        else:
            recommended_command = "make deploy"
            recommended_label = "Server deploy"
        return {
            "host_repo_path_set": bool(host_repo_path),
            "docker_socket_available": docker_sock,
            "upgrade_ready": bool(host_repo_path) and docker_sock,
            "upgrade_in_progress": self._upgrade_in_progress,
            "deployment_mode": deployment_mode,
            "recommended_command": recommended_command,
            "recommended_label": recommended_label,
            "gui_upgrade_supported": bool(host_repo_path) and docker_sock,
        }

    def verify_post_upgrade(self) -> dict[str, Any]:
        """Post-upgrade verification (UP-011).

        Checks all services, verifies version changed, checks migration status.
        Returns overall verdict: 'healthy', 'degraded', or 'unhealthy'.
        """
        checks: dict[str, dict[str, Any]] = {}

        # 1. Version verification
        upgrade_state = self.get_upgrade_state()
        version_paths = ["/app/VERSION", "/VERSION", "VERSION", "/app/data/VERSION"]
        current_version = "unknown"
        for vp in version_paths:
            if os.path.exists(vp):
                with open(vp) as f:
                    current_version = f.read().strip()
                break

        expected_version = upgrade_state.get("new_version") if upgrade_state else None
        if expected_version and current_version == expected_version:
            checks["version"] = {"status": "pass", "current": current_version, "expected": expected_version}
        elif expected_version:
            checks["version"] = {"status": "fail", "current": current_version, "expected": expected_version,
                                 "error": f"Expected {expected_version}, got {current_version}"}
        else:
            checks["version"] = {"status": "pass", "current": current_version, "note": "No expected version to compare"}

        # 2. Database health
        try:
            self.db.execute(text("SELECT 1"))
            checks["database"] = {"status": "pass"}
        except Exception as e:
            checks["database"] = {"status": "fail", "error": str(e)}

        # 3. Schema check. There is no migration head to compare a revision
        # against any more — Phase 4 dropped Alembic and the schema is created
        # from the ORM models at startup. What is worth verifying after an
        # upgrade is that every table the models declare is actually present
        # in the database file we came up on.
        try:
            from database import Base

            existing = set(inspect(self.db.get_bind()).get_table_names())
            missing = sorted(set(Base.metadata.tables) - existing)
            if missing:
                checks["schema"] = {
                    "status": "fail",
                    "missing_tables": missing,
                    "error": f"{len(missing)} table(s) declared by the models are absent",
                }
            else:
                checks["schema"] = {"status": "pass", "table_count": len(Base.metadata.tables)}
        except Exception as e:
            checks["schema"] = {"status": "skip", "note": f"Could not check: {e}"}

        # Overall verdict
        statuses = [c["status"] for c in checks.values()]
        if all(s == "pass" for s in statuses):
            verdict = "healthy"
        elif any(s == "fail" for s in statuses):
            verdict = "unhealthy"
        else:
            verdict = "degraded"

        return {
            "verdict": verdict,
            "checks": checks,
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }

    def trigger_upgrade(self) -> dict[str, Any]:
        """Trigger a system upgrade via upgrade.sh with live output streaming."""
        # Pre-flight checks
        readiness = self.get_upgrade_readiness()
        if not readiness["upgrade_ready"]:
            missing = []
            if not readiness["host_repo_path_set"]:
                missing.append("HOST_REPO_PATH not set in docker-compose.yml")
            if not readiness["docker_socket_available"]:
                missing.append("Docker socket not mounted (see docker-compose.override.example.yml)")
            return {
                "status": "not_configured",
                "message": f"GUI upgrade not available: {'; '.join(missing)}",
                "readiness": readiness,
            }

        if self._upgrade_in_progress:
            return {
                "status": "already_upgrading",
                "message": "An upgrade is already in progress",
            }

        version_info = self.get_system_version()
        if not version_info.get("update_available"):
            return {
                "status": "no_update",
                "message": "System is already at the latest version",
                "current_version": version_info.get("current_version")
            }

        # ---- UP-010: Pre-upgrade safety checks ----

        # 1. Verify Docker daemon is responsive
        try:
            docker_check = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True, text=True, timeout=10
            )
            if docker_check.returncode != 0:
                return {
                    "status": "docker_error",
                    "message": "Docker daemon is not responding. Cannot start upgrade.",
                    "error": docker_check.stderr.strip() or "docker info failed",
                }
        except subprocess.TimeoutExpired:
            return {
                "status": "docker_error",
                "message": "Docker daemon timed out. Cannot start upgrade.",
            }
        except FileNotFoundError:
            return {
                "status": "docker_error",
                "message": "Docker CLI not found. Cannot start upgrade.",
            }

        # 2. Record current git commit SHA for rollback reference
        pre_upgrade_commit = None
        try:
            git_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=os.environ.get("HOST_REPO_PATH", "/app")
            )
            if git_result.returncode == 0:
                pre_upgrade_commit = git_result.stdout.strip()
        except Exception:
            pass  # Not critical — upgrade.sh also records commit

        old_version = version_info.get("current_version", "unknown")
        new_version = version_info.get("latest_version", "unknown")
        logger.info(f"Starting system upgrade: {old_version} -> {new_version}"
                     f" (pre-commit: {pre_upgrade_commit or 'unknown'})")

        # Persist initial upgrade state BEFORE spawning thread (uses request-scoped session)
        upgrade_state: dict[str, Any] = {
            "status": "in_progress",
            "old_version": old_version,
            "new_version": new_version,
            "started_at": datetime.now(UTC).isoformat() + "Z",
            "completed_at": None,
            "current_phase": "start",
            "phase_label": "Initializing upgrade",
            "pre_upgrade_commit": pre_upgrade_commit,
            "log": [],
        }
        self._save_upgrade_state(upgrade_state)

        # Phase labels for human-readable progress messages
        _phase_labels = {
            "start": "Initializing upgrade",
            "pull": "Pulling latest code",
            "build": "Building containers",
            "restart": "Restarting services",
            "migrate": "Running database migrations",
            "verify": "Verifying health",
            "complete": "Upgrade complete",
            "failed": "Upgrade failed",
        }

        def _publish_upgrade_msg(line: str, level: str = "info", phase: str | None = None):
            """Push an upgrade message straight to connected WebSocket clients."""
            from services.websocket_service import broadcast_sync

            msg: dict[str, Any] = {
                "type": "system_upgrade",
                "level": level,
                "line": line,
                "timestamp": datetime.now(UTC).isoformat() + "Z",
            }
            if phase:
                msg["phase"] = phase
                msg["phase_label"] = _phase_labels.get(phase, phase)
            broadcast_sync(msg)

        # Exit code descriptions from upgrade.sh
        _exit_code_msgs = {
            1: "Docker Compose not found on the system",
            2: "Docker image build failed — no changes applied, system still on old version",
            3: "Failed to restart services — containers may be in a bad state",
            4: "Database migration failed — services running but DB may be inconsistent",
            5: "Services did not become healthy within timeout",
        }

        # Keep limited log buffer for DB persistence (avoid unbounded growth)
        _MAX_LOG_LINES = 200

        def _persist_phase(phase: str, status: str = "in_progress",
                           log_lines: list[str] | None = None) -> None:
            """Helper to persist upgrade phase to DB from the background thread."""
            label = _phase_labels.get(phase, phase)
            state: dict[str, Any] = {
                "status": status,
                "old_version": old_version,
                "new_version": new_version,
                "started_at": upgrade_state["started_at"],
                "completed_at": datetime.now(UTC).isoformat() + "Z" if status in ("completed", "failed") else None,
                "current_phase": phase,
                "phase_label": label,
                "log": (log_lines or [])[-_MAX_LOG_LINES:],
            }
            SystemService._save_upgrade_state_standalone(state)

        def run_upgrade():
            current_phase = "start"
            log_lines: list[str] = []
            try:
                SystemService._upgrade_in_progress = True
                _publish_upgrade_msg(
                    f"Starting upgrade: {old_version} -> {new_version}",
                    "info", phase="start"
                )
                log_lines.append(f"Starting upgrade: {old_version} -> {new_version}")

                host_repo_path = os.environ.get("HOST_REPO_PATH", "")
                host_user_home = os.environ.get(
                    "HOST_USER_HOME",
                    f"/home/{host_repo_path.split('/')[2] if len(host_repo_path.split('/')) > 2 else 'root'}"
                )

                _publish_upgrade_msg("Launching upgrade container...", "info")
                log_lines.append("Launching upgrade container...")

                docker_cmd = [
                    "docker", "run", "--rm",
                    "-v", f"{host_repo_path}:/repo",
                    "-v", "/var/run/docker.sock:/var/run/docker.sock",
                    "-v", f"{host_user_home}/.gitconfig:/root/.gitconfig:ro",
                    "-w", "/repo", "--network", "host",
                    "docker:cli", "sh", "-c",
                    "apk add --no-cache bash git && bash upgrade.sh"
                ]
                process = subprocess.Popen(docker_cmd, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True)
                try:
                    for line in iter(process.stdout.readline, ''):
                        if not line:
                            break
                        stripped = line.rstrip()

                        # Parse ##PHASE:xxx markers from upgrade.sh
                        if stripped.startswith("##PHASE:"):
                            current_phase = stripped[8:]  # e.g. "build", "restart", "failed"
                            level = "error" if current_phase == "failed" else "info"
                            label = _phase_labels.get(current_phase, current_phase)
                            logger.info(f"[upgrade] Phase: {current_phase} ({label})")
                            _publish_upgrade_msg(label, level, phase=current_phase)
                            log_lines.append(f"[PHASE] {label}")
                            # Persist phase transition to DB
                            _persist_phase(current_phase, log_lines=log_lines)
                        else:
                            logger.info(f"[upgrade] {stripped}")
                            # Detect error-level lines from the script output
                            level = "info"
                            if stripped.startswith("ERROR:") or stripped.startswith("  ERROR:"):
                                level = "error"
                            elif stripped.startswith("WARNING:") or stripped.startswith("  WARNING:"):
                                level = "warning"
                            _publish_upgrade_msg(stripped, level)
                            log_lines.append(stripped)
                except Exception:
                    pass

                exit_code = process.wait()
                if exit_code != 0:
                    error_msg = _exit_code_msgs.get(exit_code, f"Unknown error (exit code {exit_code})")
                    logger.error(f"Upgrade failed with exit code {exit_code}: {error_msg}")
                    _publish_upgrade_msg(
                        f"Upgrade failed: {error_msg}",
                        "error", phase="failed"
                    )
                    log_lines.append(f"ERROR: {error_msg}")
                    _persist_phase("failed", status="failed", log_lines=log_lines)
                else:
                    _publish_upgrade_msg(
                        f"Upgrade complete: {old_version} -> {new_version}",
                        "success", phase="complete"
                    )
                    log_lines.append(f"Upgrade complete: {old_version} -> {new_version}")
                    _persist_phase("complete", status="completed", log_lines=log_lines)
            except Exception as e:
                logger.error(f"Upgrade failed: {e}")
                _publish_upgrade_msg(f"Upgrade failed: {e}", "error", phase="failed")
                log_lines.append(f"ERROR: {e}")
                _persist_phase("failed", status="failed", log_lines=log_lines)
            finally:
                SystemService._upgrade_in_progress = False

        upgrade_thread = threading.Thread(target=run_upgrade, daemon=True)
        upgrade_thread.start()

        return {
            "status": "upgrading",
            "message": f"Upgrade started: {old_version} -> {new_version}. Services will restart.",
            "old_version": old_version, "new_version": new_version,
            "note": "The backend will restart. Watch the output log below for progress."
        }
