"""
System administration and monitoring endpoints.

Thin HTTP handlers delegating to SystemService, WorkspaceManager,
ModuleLockService, and defaults_service.
"""

import json
import logging
import os
import shutil
import tempfile
import time

import httpx
import psutil
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from core.errors import BadRequestError, handle_route_errors
from core.maintenance import get_maintenance_status
from database import get_db
from schemas.backup import BackupCreateRequest, BackupStatusResponse, MaintenanceStatusResponse, RestoreResponse
from schemas.system import SystemHealthResponse
from services.backup_service import BackupService
from services.system_service import SystemService

logger = logging.getLogger(__name__)

def _cleanup_file(path: str) -> None:
    """Remove a temporary file after the response has been sent."""
    try:
        if os.path.exists(path):
            os.unlink(path)
    except OSError as exc:
        logger.warning("Failed to clean up backup file %s: %s", path, exc)

router = APIRouter(prefix="/api/system", tags=["system"])

# Separate router for public endpoints (no auth required)
public_router = APIRouter(prefix="/api/system", tags=["system"])

# ============================================================
# Request Models
# ============================================================

class CleanupRequest(BaseModel):
    cleanup_type: str
    older_than_days: int = 30

class DefaultsUpdateRequest(BaseModel):
    updates: dict[str, str]

# ============================================================
# Service Health Endpoints
# ============================================================

@public_router.get("/health", response_model=SystemHealthResponse)
@handle_route_errors("system health check")
def get_system_health(db: Session = Depends(get_db)):
    """Get comprehensive system health status."""
    return SystemService(db).get_health()

@public_router.get("/maintenance", response_model=MaintenanceStatusResponse)
@handle_route_errors("get maintenance status")
def get_maintenance_mode():
    """Get current maintenance mode status. No auth required."""
    status = get_maintenance_status()
    if status:
        return MaintenanceStatusResponse(
            maintenance_mode=True,
            message=status.get("message"),
            started_at=status.get("started_at"),
        )
    return MaintenanceStatusResponse(maintenance_mode=False)

# ============================================================
# Process Metrics — backend self-monitoring for header strip
# ============================================================

# psutil.Process().cpu_percent() returns a delta since the last call, so we
# hold a single long-lived Process instance and initialize it at import time.
_self_process = psutil.Process(os.getpid())
_self_process.cpu_percent(interval=None)  # prime so first real call is accurate
_process_start_time = _self_process.create_time()

class ProcessMetricsResponse(BaseModel):
    cpu_percent: float
    cpu_count: int
    rss_bytes: int
    vms_bytes: int
    num_threads: int
    open_fds: int | None
    net_rx_bytes: int
    net_tx_bytes: int
    uptime_seconds: int
    sampled_at: float  # unix seconds — frontend diffs this to compute net rates

@public_router.get("/process-metrics", response_model=ProcessMetricsResponse)
@handle_route_errors("process metrics")
def get_process_metrics() -> ProcessMetricsResponse:
    """
    Return CPU / memory / network metrics for the backend process itself.

    Used by the persistent metrics strip in the web UI header. The network
    counters are the absolute byte totals since container start; the frontend
    diffs consecutive samples to compute rates.
    """
    mem = _self_process.memory_info()
    # cpu_percent without interval returns the delta since the previous call —
    # this is the cheap, non-blocking form suitable for a polled endpoint.
    cpu = _self_process.cpu_percent(interval=None)

    try:
        fds = _self_process.num_fds()  # Linux/macOS only
    except (AttributeError, psutil.AccessDenied):
        fds = None

    # psutil.net_io_counters() reports the process's network namespace — in a
    # container, that's the container-wide counter, which is effectively "this
    # program" for our purposes.
    nio = psutil.net_io_counters()

    return ProcessMetricsResponse(
        cpu_percent=round(cpu, 2),
        cpu_count=psutil.cpu_count(logical=True) or 1,
        rss_bytes=mem.rss,
        vms_bytes=mem.vms,
        num_threads=_self_process.num_threads(),
        open_fds=fds,
        net_rx_bytes=nio.bytes_recv,
        net_tx_bytes=nio.bytes_sent,
        uptime_seconds=int(time.time() - _process_start_time),
        sampled_at=time.time(),
    )

# ============================================================
# Performance Metrics
# ============================================================

@router.get("/performance")
@handle_route_errors("performance metrics")
def get_performance_metrics(db: Session = Depends(get_db)):
    """Get system performance metrics."""
    return SystemService(db).get_performance_metrics()

# ============================================================
# Recent Errors
# ============================================================

@router.get("/errors")
@handle_route_errors("get recent errors")
def get_recent_errors(limit: int = 10, db: Session = Depends(get_db)):
    """Get recent failed tasks and errors."""
    return SystemService(db).get_recent_errors(limit=limit)

# ============================================================
# Database Management
# ============================================================

@router.post("/database/vacuum")
@handle_route_errors("database vacuum")
def vacuum_database(db: Session = Depends(get_db)):
    """Reclaim free pages in the SQLite file (VACUUM)."""
    result = SystemService(db).vacuum_database()
    db.commit()
    return result

# ============================================================
# System Defaults (delegates to defaults_service)
# ============================================================

@router.get("/defaults")
@handle_route_errors("get system defaults")
def get_system_defaults(db: Session = Depends(get_db)):
    """Get all system defaults organized by category."""
    from services.defaults_service import get_all_defaults
    return get_all_defaults(db)

@router.get("/defaults/status")
@handle_route_errors("check defaults status")
def get_defaults_status(db: Session = Depends(get_db)):
    """Check if all required system defaults are configured."""
    from services.defaults_service import check_required_configured
    return check_required_configured(db)

@router.put("/defaults")
@handle_route_errors("update system defaults")
def update_system_defaults(request: DefaultsUpdateRequest, db: Session = Depends(get_db)):
    """Update multiple system defaults at once."""
    from services.defaults_service import set_defaults_batch
    results = set_defaults_batch(db, request.updates)
    failed = [k for k, v in results.items() if not v]
    # ENG-006: Route owns the transaction boundary
    db.commit()
    if failed:
        return {"status": "partial", "results": results, "failed": failed}
    return {"status": "success", "results": results}

@router.put("/defaults/{key}")
@handle_route_errors("update single default")
def update_single_default(key: str, value: str, db: Session = Depends(get_db)):
    """Update a single system default."""
    import urllib.parse

    from services.defaults_service import set_default
    decoded_key = urllib.parse.unquote(key)
    success = set_default(db, decoded_key, value)
    if not success:
        raise BadRequestError(f"Invalid setting key: {decoded_key}", code="INVALID_SETTING_KEY")
    # ENG-006: Route owns the transaction boundary
    db.commit()
    return {"status": "success", "key": decoded_key}

# ============================================================
# System Version & Upgrade
# ============================================================

@router.get("/version")
@handle_route_errors("get system version")
def get_system_version(db: Session = Depends(get_db)):
    """Get current and available system versions, plus upgrade readiness."""
    svc = SystemService(db)
    result = svc.get_system_version()
    # Merge upgrade readiness into version response so UI can show warnings
    result["upgrade_readiness"] = svc.get_upgrade_readiness()
    return result

@router.get("/upgrade/status")
@handle_route_errors("get upgrade status")
def get_upgrade_status(db: Session = Depends(get_db)):
    """Get persisted upgrade state (UP-003).

    Returns the last/current upgrade state from the DB.
    The frontend uses this to recover state after a page refresh or
    reconnection during an upgrade.
    """
    from schemas.system import UpgradeStateResponse

    svc = SystemService(db)
    state = svc.get_upgrade_state()
    if state is None:
        return UpgradeStateResponse(status="none").model_dump()

    # If the DB says in_progress but the class variable says no upgrade running,
    # the backend restarted mid-upgrade. Mark it as unknown/stale.
    if state.get("status") == "in_progress" and not SystemService.is_upgrade_in_progress():
        state["status"] = "interrupted"
        state["phase_label"] = "Upgrade was interrupted (backend restarted)"

    return UpgradeStateResponse(**state).model_dump()

@router.get("/upgrade/verify")
@handle_route_errors("verify post-upgrade health")
def verify_post_upgrade(db: Session = Depends(get_db)):
    """Post-upgrade verification (UP-011).

    Checks all services health, verifies version changed, checks migrations.
    Call this after an upgrade completes to get detailed verification results.
    """
    return SystemService(db).verify_post_upgrade()

@router.post("/upgrade")
@handle_route_errors("trigger system upgrade")
def trigger_system_upgrade(db: Session = Depends(get_db)):
    """Trigger a system upgrade with live output streaming via WebSocket."""
    return SystemService(db).trigger_upgrade()

# ============================================================
# MCP Server Status
# ============================================================

@router.get("/mcp/status")
@handle_route_errors("MCP server status")
def get_mcp_status():
    """Check MCP server health and return tool catalog.

    Probes the MCP container via JSON-RPC ping and returns connection
    info, health status, and the full tool catalog grouped by domain.
    """
    # Try container name first (bridge networking), then localhost (host networking)
    mcp_urls = ["http://bnkscope-mcp:8081/mcp", "http://localhost:8081/mcp"]
    status = "offline"
    latency_ms: float | None = None
    error_message: str | None = None
    reachable_url: str | None = None

    # Probe MCP health via JSON-RPC ping (must be POST per MCP protocol)
    for mcp_url in mcp_urls:
        try:
            start = time.monotonic()
            resp = httpx.post(
                mcp_url,
                json={"jsonrpc": "2.0", "method": "ping", "id": 1},
                headers={"Accept": "application/json,text/event-stream", "Content-Type": "application/json"},
                timeout=5.0,
            )
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            if resp.status_code < 500:
                status = "healthy"
                reachable_url = mcp_url
            else:
                status = "degraded"
                error_message = f"HTTP {resp.status_code}"
                reachable_url = mcp_url
            break  # Success — stop trying other URLs
        except (httpx.ConnectError, httpx.TimeoutException):
            continue  # Try next URL
        except Exception as e:
            error_message = str(e)
            break

    if status == "offline" and not error_message:
        error_message = "Cannot connect to MCP container"

    # Presentation-only map: module key → (display label, icon).
    # This is the ONLY static data — labels and icons cannot come from the server.
    # Any tool whose module is not in this map falls into the "Other" bucket.
    _MODULE_DISPLAY: dict[str, tuple[str, str]] = {
        "system": ("System", "Server"),
        "cluster_management": ("Cluster Management", "Box"),
        "bnk_operations": ("F5 BNK Operations", "Shield"),
        "diagnostics_fleet": ("Diagnostics", "Globe"),
    }

    tool_catalog: list[dict] = []
    total_tools = 0

    if reachable_url is not None:
        # Perform MCP Streamable-HTTP handshake then fetch tools/list.
        # The MCP server may reply as SSE (data: {...} lines) or plain JSON — handle both.

        def _parse_mcp_response(resp: httpx.Response) -> dict:
            """Parse either plain JSON or SSE-wrapped JSON from an MCP response."""
            ct = resp.headers.get("content-type", "")
            if "text/event-stream" in ct:
                for line in resp.text.splitlines():
                    line = line.strip()
                    if line.startswith("data:"):
                        payload = line[len("data:") :].strip()
                        if payload and payload != "[DONE]":
                            return dict(json.loads(payload))
                return {}
            return dict(resp.json())

        try:
            common_headers = {
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            }
            session_id: str | None = None

            init_resp = httpx.post(
                reachable_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "id": 1,
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "bnkscope-backend", "version": "1"},
                    },
                },
                headers=common_headers,
                follow_redirects=True,
                timeout=10.0,
            )
            session_id = init_resp.headers.get("mcp-session-id")

            notify_headers = dict(common_headers)
            if session_id:
                notify_headers["mcp-session-id"] = session_id

            httpx.post(
                reachable_url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=notify_headers,
                follow_redirects=True,
                timeout=5.0,
            )

            list_resp = httpx.post(
                reachable_url,
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 2, "params": {}},
                headers=notify_headers,
                follow_redirects=True,
                timeout=10.0,
            )
            list_data = _parse_mcp_response(list_resp)
            raw_tools: list[dict] = list_data.get("result", {}).get("tools") or []

            # Group by module; unknown/missing module → "Other"
            buckets: dict[str, list[dict]] = {}
            for t in raw_tools:
                tool_meta = t.get("_meta") or t.get("meta") or {}
                module = tool_meta.get("module") or ""
                buckets.setdefault(module, []).append(
                    {"name": t.get("name", ""), "description": t.get("description", "")}
                )

            # Emit categories in MODULE_DISPLAY order, then "Other"
            for mod_key, (label, icon) in _MODULE_DISPLAY.items():
                tools_in_cat = sorted(buckets.pop(mod_key, []), key=lambda x: x["name"])
                if tools_in_cat:
                    tool_catalog.append({"category": label, "icon": icon, "tools": tools_in_cat})

            # Remaining buckets (unknown modules) → "Other"
            other_tools: list[dict] = []
            for leftover in buckets.values():
                other_tools.extend(leftover)
            other_tools.sort(key=lambda x: x["name"])
            if other_tools:
                tool_catalog.append({"category": "Other", "icon": "Wrench", "tools": other_tools})

            total_tools = sum(len(cat["tools"]) for cat in tool_catalog)

        except Exception as e:
            logger.warning("MCP tools/list handshake failed: %s", e)
            if status == "healthy":
                status = "degraded"
            error_message = f"Tool catalog unavailable: {e}"
            tool_catalog = []
            total_tools = 0

    return {
        "status": status,
        "latency_ms": latency_ms,
        "error": error_message,
        "endpoint": "/mcp/",
        "port": 8081,
        "transport": "Streamable HTTP",
        "total_tools": total_tools,
        "tool_catalog": tool_catalog,
    }

# ============================================================
# Backup & Restore Endpoints
# ============================================================

@router.post("/backup")
@handle_route_errors("create backup")
def create_backup(request: BackupCreateRequest, db: Session = Depends(get_db)):
    """Create a backup archive. Returns the archive as a streaming file download."""
    service = BackupService(db)
    archive_path = service.create_backup(request.passphrase)
    filename = os.path.basename(archive_path)
    return FileResponse(
        path=archive_path,
        media_type="application/gzip",
        filename=filename,
        background=BackgroundTask(_cleanup_file, archive_path),
    )

@router.get("/backup/status", response_model=BackupStatusResponse)
@handle_route_errors("get backup status")
def get_backup_status(db: Session = Depends(get_db)):
    """Check whether a backup/restore operation is currently in progress."""
    service = BackupService(db)
    return service.get_backup_status()

@router.post("/restore", response_model=RestoreResponse)
@handle_route_errors("restore backup")
async def restore_backup(
    file: UploadFile = File(..., description="Backup archive (.tar.gz)"),
    passphrase: str = Form(..., min_length=12, description="Archive passphrase"),
    db: Session = Depends(get_db),
):
    """
    Restore a backup archive.

    This is a destructive operation. The system will:
    1. Enter maintenance mode (503 for all other requests)
    2. Restore the database
    3. Run any needed migrations
    4. Replace the encryption key
    5. Restart the backend (to reload the new key)

    The backend will restart automatically after restore completes.
    Poll /api/system/health to detect when it's back online.
    """
    # Save uploaded file to temp location
    tmp_archive = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz")
    try:
        shutil.copyfileobj(file.file, tmp_archive)
        tmp_archive.close()

        service = BackupService(db)
        result = service.restore_backup(tmp_archive.name, passphrase)

        # Schedule restart AFTER the response has been fully sent.
        # We use a background function that Starlette runs post-response,
        # then add a small buffer before calling os._exit() to ensure the
        # connection is closed cleanly through the proxy chain.
        def _trigger_restart() -> None:
            logger.info("Response sent — scheduling process termination")
            time.sleep(3)  # Let Uvicorn/nginx fully close the connection
            logger.info("Triggering backend restart after restore")
            os._exit(0)  # Docker Compose will restart us

        response = RestoreResponse(**result)
        # Starlette's BackgroundTask fires after the HTTP response is written
        background = BackgroundTask(_trigger_restart)
        # Attach via raw Response so the task runs post-send
        from starlette.responses import JSONResponse as StarletteJSONResponse
        return StarletteJSONResponse(
            content=response.model_dump(),
            background=background,
        )

    finally:
        # Clean up temp file
        if os.path.exists(tmp_archive.name):
            os.unlink(tmp_archive.name)
