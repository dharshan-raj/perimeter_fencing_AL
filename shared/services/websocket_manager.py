# ============================================================
# FILE: shared/services/websocket_manager.py
# PURPOSE: Manages WebSocket connections for real-time event
#          broadcasting to the React frontend dashboard.
# USE CASE: All (Shared — used by main.py for all 3 use cases)
#
# HOW IT WORKS:
#   - ConnectionManager maintains a set of active WebSocket clients.
#   - broadcast() sends a JSON payload to all connected clients.
#   - Dead connections are automatically removed on send failure.
#   - main.py calls: await manager.broadcast(payload)
#
# DEBUG TIPS:
#   - Frontend not receiving real-time events?
#       → Open browser DevTools → Network → WS tab.
#       → Confirm WebSocket connection to ws://localhost:8000/ws is established.
#       → Check CORS settings in main.py (allow_origins must include frontend URL).
#   - "WebSocket connection refused"?
#       → Backend may not be running. Check: http://localhost:8000/api/health
#   - Events delayed or missing?
#       → WebSocket is async. Events from camera thread use asyncio.run_coroutine_threadsafe().
#       → Check publish_from_thread() in main.py — requires event loop to be running.
#   - Multiple broadcast failures?
#       → Dead connections are cleaned up automatically on each broadcast.
#       → Check frontend reconnects on disconnect (React useEffect cleanup).
#
# FRONTEND CONNECTION:
#   const ws = new WebSocket("ws://localhost:8000/ws");
#   ws.onmessage = (e) => { const data = JSON.parse(e.data); ... }
#
# DEPENDENCIES:
#   - fastapi WebSocket  → accept, send_json
# ============================================================

from fastapi import WebSocket


class ConnectionManager:
    """
    Manages a set of active WebSocket client connections.
    Broadcasts JSON payloads to all connected clients simultaneously.
    """

    def __init__(self):
        self.clients: set = set()

    async def connect(self, ws: WebSocket):
        """Accept a new WebSocket connection and register it."""
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        """Remove a WebSocket client from the active set."""
        self.clients.discard(ws)

    async def broadcast(self, payload):
        """
        Send payload as JSON to all connected WebSocket clients.
        Automatically removes dead/disconnected clients on failure.

        Args:
            payload (dict): JSON-serializable event data.

        DEBUG: Empty clients set?
               → No frontend is connected. Check WebSocket URL in React frontend.
               → Verify: ws://localhost:8000/ws matches the FastAPI @app.websocket("/ws") route.
        """
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# Singleton instance — imported and used by main.py
manager = ConnectionManager()
