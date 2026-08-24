"""WebSocket fan-out to connected UI clients.

This used to publish through Redis pub/sub, because the producers were Celery
worker *processes* and the WebSocket connections lived in the API process.
bnkscope runs in one process (Phase 4), so a producer can hand the message
straight to the connection manager.

``broadcast_sync`` exists for callers on a worker thread (core/background.py)
that have no event loop of their own; it hops onto the app's loop.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

class WebSocketManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Unregister a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected WebSocket clients."""
        if not self.active_connections:
            return

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to WebSocket: {e}")
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    async def send_ping(self):
        """Send ping to all connected clients to keep connections alive."""
        ping_message = {
            "type": "ping",
            "timestamp": datetime.now(UTC).isoformat() + 'Z'
        }
        await self.broadcast(ping_message)


# Global WebSocket manager instance
ws_manager = WebSocketManager()


# The app's event loop, captured at startup so threads can schedule onto it.
_loop: asyncio.AbstractEventLoop | None = None


def bind_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Record the loop that owns the WebSocket connections."""
    global _loop
    _loop = loop


def broadcast_sync(message: dict[str, Any]) -> None:
    """Broadcast from a non-async context (a background thread).

    Best-effort: if the loop is not running yet, or the send fails, the message
    is dropped with a debug log. WebSocket updates are a live view, not a
    delivery guarantee — the UI refetches on reconnect.
    """
    loop = _loop
    if loop is None or not loop.is_running():
        logger.debug("broadcast_sync dropped a message: no running event loop")
        return
    try:
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(message), loop)
    except Exception as exc:  # noqa: BLE001 — never break the caller
        logger.debug("broadcast_sync failed: %s", exc)


async def keepalive_task():
    """Send periodic pings to keep WebSocket connections alive."""
    while True:
        try:
            await asyncio.sleep(30)
            await ws_manager.send_ping()
        except asyncio.CancelledError:
            logger.info("Keepalive task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in keepalive task: {e}")
