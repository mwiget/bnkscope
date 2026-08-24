"""bnkscope API — application entry point.

One process: the HTTP API, the WebSocket fan-out, the reachability probe loop,
the periodic jobs, and a small thread pool for background work. Celery, Redis
and Postgres went in Phase 4; nothing here talks to another service.
"""
import asyncio
import atexit
import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi import HTTPException as FastAPIHTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# Import core modules
from core.config import settings
from core.errors import (
    AppError,
    app_error_handler,
    general_exception_handler,
    http_exception_handler,
)
from core.logging_config import configure_logging
from core.maintenance import clear_maintenance_mode
from core.maintenance_middleware import MaintenanceMiddleware

# DEVOPS-004: Configure structured logging before anything else logs
configure_logging(
    environment=settings.ENVIRONMENT,
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    service_name=settings.APP_NAME
)

# Import database
from database import SessionLocal  # noqa: F401 — used by route handlers via get_db()
from routes.alert_channels import router as alert_channels_router

# NOTE: KubernetesSync and TerragruntSync imports removed in v2.0.1
# Sync is now project-based via routes/api.py and routes/projects.py
# Import all routers
from routes.api import router as api_router
from routes.connectivity import router as connectivity_router
from routes.k8s import (
    clusters_router,
    crds_router,
    dpf_router,
    f5bnk_router,
    llm_observability_router,
    recovery_router,
    resources_router,
    tmm_debug_router,
    topology_router,
)
from routes.k8s_websocket import router as k8s_websocket_router
from routes.logs import router as logs_router
from routes.notifications import router as notifications_router
from routes.notifications import ws_router as notifications_ws_router
from routes.qkview import router as qkview_router
from routes.system import public_router as system_public_router
from routes.system import router as system_router
from routes.tmmscope import router as tmmscope_router

# Get logger (logging already configured via configure_logging above)
logger = logging.getLogger(__name__)

# Initialize background scheduler
scheduler = BackgroundScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - handles startup and shutdown"""
    from startup_steps import (
        discover_clusters_step,
        init_database_step,
        publish_log_collector_step,
        seed_defaults_step,
        start_scheduler_step,
    )

    # Startup
    logger.info("=" * 60)
    logger.info("bnkscope starting")
    logger.info("=" * 60)

    # Database init and lock-column assertion are fatal — everything else is best-effort.
    # assert_lock_columns_step calls sys.exit(1) if migration hasn't been run.
    # init_database_step creates the schema from the ORM metadata and verifies
    # the connection; there is nothing else the app cannot start without.
    FATAL_STEPS = [("Database", init_database_step)]
    # The flag is in-process now, so a fresh start cannot inherit a stale one;
    # this stays as a cheap assertion of that.
    clear_maintenance_mode()

    BEST_EFFORT_STEPS = [
        ("System defaults", seed_defaults_step),
        # Before the scheduler, so Alloy finds a config on its first boot
        # rather than waiting out the first interval.
        ("Log collector", publish_log_collector_step),
        ("Scheduler", lambda: start_scheduler_step(scheduler)),
        # Last, and non-blocking: it only hands work to the background pool.
        ("Cluster discovery", discover_clusters_step),
    ]

    for name, step in FATAL_STEPS:
        try:
            step()
            logger.info(f"✓ {name}")
        except Exception as e:
            logger.critical(f"✗ {name}: {e}")
            raise SystemExit(f"Cannot start without {name}: {e}")

    for name, step in BEST_EFFORT_STEPS:
        try:
            # Run each step in a thread pool thread so the event loop stays
            # responsive during DB I/O. Each step owns its own DB session via
            # get_db_context(), so thread execution is safe.
            await asyncio.to_thread(step)
            logger.info(f"✓ {name}")
        except Exception as e:
            logger.error(f"✗ {name}: {e}")

    # WebSocket fan-out. bind_event_loop lets background threads schedule a
    # broadcast onto this loop (services/websocket_service.broadcast_sync).
    keepalive_task = None
    try:
        from services.websocket_service import bind_event_loop
        from services.websocket_service import keepalive_task as keepalive_fn
        bind_event_loop(asyncio.get_running_loop())
        keepalive_task = asyncio.create_task(keepalive_fn())
        logger.info("✓ WebSocket service")
    except Exception as e:
        logger.error(f"✗ WebSocket service: {e}")

    # Start reachability subsystem (async scheduler, one task per probe class).
    # Failure here must NOT block startup — connectivity is observability, not
    # the request path.
    try:
        from database import SessionLocal as _SessionLocal
        from services.reachability import registry as _reach_registry
        from services.reachability.probes.cluster import ClusterProbe
        _reach_registry.configure(db_session_factory=_SessionLocal)
        _reach_registry.register(ClusterProbe(db_session_factory=_SessionLocal))
        await _reach_registry.start()
        logger.info("✓ Reachability scheduler")
    except Exception as e:
        logger.error(f"✗ Reachability scheduler: {e}")

    logger.info("=" * 60)
    logger.info("bnkscope ready")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("Shutting down bnkscope...")


    # Stop reachability scheduler
    try:
        from services.reachability import registry as _reach_registry
        await _reach_registry.stop()
    except Exception as e:
        logger.warning(f"Reachability scheduler shutdown error: {e}")

    # Stop WebSocket keepalive
    if keepalive_task:
        keepalive_task.cancel()
        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass

    if scheduler.running:
        scheduler.shutdown()

    # Drain the background thread pool.
    from core.background import shutdown as shutdown_background
    shutdown_background()

# Create FastAPI app with lifespan
app = FastAPI(title="bnkscope API", version=settings.VERSION, lifespan=lifespan)

# Security Headers Middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"  # Allow iframes from same origin
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Horizon 3 prep: API version headers for debugging and future API versioning
        response.headers["X-Bnkscope-Version"] = settings.VERSION
        response.headers["X-BNK-Forge-API"] = "v1"
        return response

# OBS-001: Correlation ID Middleware — must be outermost (added first, runs last)
# Generates X-Request-ID for every request and propagates via contextvars
from core.correlation import CorrelationMiddleware

app.add_middleware(CorrelationMiddleware)

app.add_middleware(SecurityHeadersMiddleware)

# CORS — off unless someone asks for it, and nothing in the product does.
#
# The UI reaches this API through nginx on its own origin (relative paths, a
# `/api/` proxy), so no request the app makes is cross-origin and no CORS
# header is involved. Adding the middleware with a wildcard would only grant
# access to pages that are NOT the UI — and this API has no authentication and
# will hand `POST /api/system/backup` to anyone who asks, so that grant is the
# whole credential store, from any site the operator happens to have open.
#
# ALLOWED_ORIGINS exists for running a dev server against a container backend.
# Wildcard is refused rather than honoured: it is never the right answer here,
# and it is the value that would silently reopen the hole.
allowed_origins = settings.cors_origins

if "*" in allowed_origins:
    raise RuntimeError(
        "ALLOWED_ORIGINS is set to '*'. This API has no authentication and "
        "serves the credential backup archive, so a wildcard would expose it "
        "to every page in the operator's browser. Name the origins instead, "
        "or leave it empty — the UI does not need CORS."
    )

if allowed_origins:
    logger.warning(
        "CORS enabled for %s — the UI does not need this; it is for a dev "
        "server pointed at this backend.",
        allowed_origins,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
        max_age=600,
    )
else:
    logger.info("CORS disabled — the UI is same-origin through nginx")

# Maintenance Middleware — blocks non-system requests during restore operations
# Blocks non-system requests during restore operations
app.add_middleware(MaintenanceMiddleware)

# Register shutdown with atexit as backup
atexit.register(lambda: scheduler.shutdown() if scheduler.running else None)

# Register global error handlers
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(FastAPIHTTPException, http_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Include all routers
app.include_router(api_router)
app.include_router(clusters_router)     # K8s cluster CRUD, scan
app.include_router(crds_router)         # CRD discovery
app.include_router(topology_router)     # Namespace topology graph
app.include_router(resources_router)    # K8s resource CRUD, pod/node ops, metrics
app.include_router(f5bnk_router)        # F5 BNK gateways, topology, health
app.include_router(llm_observability_router)  # AI-gateway observability — Loki request analytics
app.include_router(dpf_router)          # NVIDIA DPF — read-only DPU inventory + health
app.include_router(tmm_debug_router)    # TMM debug sidecar — tmctl, configview, bdt_cli
app.include_router(recovery_router)     # Post-reboot recovery — CWC cert re-sync, platform restart
app.include_router(notifications_router)
app.include_router(notifications_ws_router)  # WebSocket — no JWT auth (WS has no Request headers)
app.include_router(system_public_router)  # Health endpoint — no auth (Docker healthcheck)
app.include_router(system_router)
app.include_router(k8s_websocket_router)  # WebSocket routes for K8s exec and log streaming
app.include_router(alert_channels_router)  # Alert channels — webhook/Slack/Teams notifications
app.include_router(qkview_router)  # QKView — CWC diagnostic tarball collection for F5 BNK
app.include_router(tmmscope_router)  # tmmscope — read-only status of the local TMM telemetry stack
app.include_router(logs_router)  # logs — search the collected pod logs (Loki)
app.include_router(connectivity_router)  # Reachability state + SSE stream + force-probe

# Health check for quick verification
@app.get("/ping")
def ping():
    """Simple ping endpoint for health checks"""
    return {"status": "ok", "message": "BNK-Forge API is running"}
