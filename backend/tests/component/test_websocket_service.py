"""WebSocketManager and the thread-to-loop broadcast bridge.

The Redis pub/sub layer these used to exercise went in Phase 4: producers are
in-process now, so they hand messages to the manager directly. What still needs
covering is the manager's connection bookkeeping and ``broadcast_sync``, which
is the seam a background thread uses to reach the event loop.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import websocket_service
from services.websocket_service import WebSocketManager, broadcast_sync


def _fake_ws() -> MagicMock:
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


class TestWebSocketManager:
    @pytest.mark.asyncio
    async def test_connect_accepts_and_registers(self):
        mgr = WebSocketManager()
        ws = _fake_ws()
        await mgr.connect(ws)

        ws.accept.assert_awaited_once()
        assert ws in mgr.active_connections

    def test_disconnect_is_idempotent(self):
        mgr = WebSocketManager()
        ws = _fake_ws()
        mgr.active_connections.append(ws)

        mgr.disconnect(ws)
        mgr.disconnect(ws)  # must not raise
        assert ws not in mgr.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_reaches_every_client(self):
        mgr = WebSocketManager()
        a, b = _fake_ws(), _fake_ws()
        mgr.active_connections.extend([a, b])

        await mgr.broadcast({"type": "hello"})

        a.send_json.assert_awaited_once_with({"type": "hello"})
        b.send_json.assert_awaited_once_with({"type": "hello"})

    @pytest.mark.asyncio
    async def test_broadcast_drops_a_dead_client_and_keeps_going(self):
        """One broken socket must not stop the others receiving the message."""
        mgr = WebSocketManager()
        dead, alive = _fake_ws(), _fake_ws()
        dead.send_json.side_effect = RuntimeError("socket closed")
        mgr.active_connections.extend([dead, alive])

        await mgr.broadcast({"type": "hello"})

        alive.send_json.assert_awaited_once()
        assert dead not in mgr.active_connections
        assert alive in mgr.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_with_no_clients_is_a_noop(self):
        await WebSocketManager().broadcast({"type": "hello"})  # must not raise

    @pytest.mark.asyncio
    async def test_send_ping_shape(self):
        mgr = WebSocketManager()
        ws = _fake_ws()
        mgr.active_connections.append(ws)

        await mgr.send_ping()

        sent = ws.send_json.await_args.args[0]
        assert sent["type"] == "ping"
        assert sent["timestamp"]


class TestBroadcastSync:
    """The bridge background threads use to reach the loop."""

    def test_drops_the_message_when_no_loop_is_bound(self, monkeypatch):
        monkeypatch.setattr(websocket_service, "_loop", None)
        broadcast_sync({"type": "system_upgrade"})  # must not raise

    def test_drops_the_message_when_the_loop_is_not_running(self, monkeypatch):
        loop = MagicMock()
        loop.is_running.return_value = False
        monkeypatch.setattr(websocket_service, "_loop", loop)

        broadcast_sync({"type": "system_upgrade"})  # must not raise

    @pytest.mark.asyncio
    async def test_delivers_onto_a_running_loop(self, monkeypatch):
        mgr = WebSocketManager()
        ws = _fake_ws()
        mgr.active_connections.append(ws)
        monkeypatch.setattr(websocket_service, "ws_manager", mgr)
        websocket_service.bind_event_loop(asyncio.get_running_loop())

        await asyncio.to_thread(broadcast_sync, {"type": "system_upgrade", "line": "hi"})
        await asyncio.sleep(0.05)  # let the scheduled coroutine run

        ws.send_json.assert_awaited_once_with({"type": "system_upgrade", "line": "hi"})
